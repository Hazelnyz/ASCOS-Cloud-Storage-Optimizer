"""Long-poll an SQS queue and run ASCOS predictions for one user's files."""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import threading
import uuid
from collections.abc import Callable

import boto3

logger = logging.getLogger("ascos.ml.worker")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_MESSAGE_BYTES = 64 * 1024
_POLL_SECONDS = 20


def parse_message(body: object) -> dict[str, str]:
    """Validate the queue contract and return canonical user_id/run_id."""
    if not isinstance(body, str) or len(body.encode("utf-8")) > _MAX_MESSAGE_BYTES:
        raise ValueError("message body must be a UTF-8 JSON string under 64 KiB")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("message body is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("message body must be a JSON object")
    user_id = payload.get("user_id")
    run_id = payload.get("run_id")
    if not isinstance(user_id, str) or not _USER_ID_RE.fullmatch(user_id):
        raise ValueError("user_id is missing or invalid")
    if not isinstance(run_id, str):
        raise ValueError("run_id is missing or invalid")
    try:
        canonical_run_id = str(uuid.UUID(run_id))
    except (ValueError, AttributeError) as error:
        raise ValueError("run_id must be a UUID") from error
    return {"user_id": user_id, "run_id": canonical_run_id}


def _visibility_heartbeat(
    sqs,
    queue_url: str,
    receipt_handle: str,
    visibility_timeout: int,
    stop: threading.Event,
) -> None:
    interval = max(30, visibility_timeout // 2)
    while not stop.wait(interval):
        try:
            sqs.change_message_visibility(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout,
            )
        except Exception:
            # The task continues; stable IDs make a later delivery safe to repeat.
            logger.exception("could not extend SQS message visibility")


def process_message(
    sqs,
    queue_url: str,
    message: dict,
    run_inference: Callable[..., int],
    model_version: str,
    visibility_timeout: int,
) -> bool:
    """Process one receipt; invalid/failed tasks remain queued for retry/DLQ."""
    receipt_handle = message.get("ReceiptHandle")
    if not isinstance(receipt_handle, str) or not receipt_handle:
        logger.error("received SQS message without a receipt handle")
        return False

    try:
        task = parse_message(message.get("Body"))
    except ValueError as error:
        logger.error("invalid SQS task; leaving it for redrive: %s", error)
        return False

    stop_heartbeat = threading.Event()
    heartbeat = threading.Thread(
        target=_visibility_heartbeat,
        args=(sqs, queue_url, receipt_handle, visibility_timeout, stop_heartbeat),
        daemon=True,
    )
    heartbeat.start()
    try:
        run_inference(
            user_ids=[task["user_id"]],
            model_version=model_version,
            run_id=task["run_id"],
        )
    except Exception:
        logger.exception("inference failed for user_id=%s run_id=%s; leaving task for retry", task["user_id"], task["run_id"])
        return False
    finally:
        stop_heartbeat.set()
        heartbeat.join()

    try:
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
    except Exception:
        logger.exception("inference succeeded but SQS acknowledgement failed; task may be redelivered")
        return False
    logger.info("completed user_id=%s run_id=%s", task["user_id"], task["run_id"])
    return True


def poll_once(sqs, queue_url: str, run_inference: Callable[..., int], model_version: str, visibility_timeout: int) -> int:
    response = sqs.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=_POLL_SECONDS,
        VisibilityTimeout=visibility_timeout,
    )
    messages = response.get("Messages", [])
    if not messages:
        return 0
    return int(process_message(sqs, queue_url, messages[0], run_inference, model_version, visibility_timeout))


def run_worker(stop: threading.Event | None = None) -> None:
    queue_url = os.environ["SQS_QUEUE_URL"]
    model_version = os.environ["MODEL_VERSION"]
    visibility_timeout = int(os.environ.get("SQS_VISIBILITY_TIMEOUT_SECONDS", "21600"))
    if not 60 <= visibility_timeout <= 43200:
        raise ValueError("SQS_VISIBILITY_TIMEOUT_SECONDS must be between 60 and 43200")

    sqs = boto3.client("sqs")
    attributes = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["QueueArn", "VisibilityTimeout", "ReceiveMessageWaitTimeSeconds"],
    ).get("Attributes", {})
    logger.info("worker queue ready: %s", attributes.get("QueueArn", "unknown ARN"))

    from ml.inference.batch_driver import run

    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            poll_once(sqs, queue_url, run, model_version, visibility_timeout)
        except Exception:
            logger.exception("SQS polling failed; retrying")
            stop.wait(5)


def main() -> None:
    stop = threading.Event()

    def request_shutdown(signum, frame) -> None:
        logger.info("received signal %s; finishing current message before shutdown", signum)
        stop.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    run_worker(stop)


if __name__ == "__main__":
    main()
