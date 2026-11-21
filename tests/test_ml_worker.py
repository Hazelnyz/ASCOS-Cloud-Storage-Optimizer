import json
import uuid
from unittest.mock import Mock

import pytest

from ml.inference.predictor import prediction_id_for_run
from ml.worker.worker import parse_message, process_message


def test_parse_message_accepts_user_and_uuid_run_id():
    run_id = str(uuid.uuid4())
    assert parse_message(json.dumps({"user_id": "user-123", "run_id": run_id})) == {
        "user_id": "user-123",
        "run_id": run_id,
    }


@pytest.mark.parametrize("body", [
    "not json",
    "[]",
    "{}",
    '{"user_id":"user-1","run_id":"not-a-uuid"}',
    '{"user_id":"../other","run_id":"00000000-0000-0000-0000-000000000001"}',
])
def test_parse_message_rejects_invalid_tasks(body):
    with pytest.raises(ValueError):
        parse_message(body)


def test_prediction_id_is_stable_per_run_and_changes_for_a_new_run():
    run_id = str(uuid.uuid4())
    first = prediction_id_for_run("user-a", "file-a", "model-v1", run_id)
    assert first == prediction_id_for_run("user-a", "file-a", "model-v1", run_id)
    assert first != prediction_id_for_run("user-a", "file-a", "model-v1", str(uuid.uuid4()))
    assert first != prediction_id_for_run("user-b", "file-a", "model-v1", run_id)


def _message(body):
    return {"Body": body, "ReceiptHandle": "receipt-1"}


def test_message_is_deleted_only_after_inference_succeeds():
    sqs = Mock()
    run = Mock(return_value=1)
    run_id = str(uuid.uuid4())
    ok = process_message(
        sqs,
        "https://sqs.example/queue",
        _message(json.dumps({"user_id": "user-a", "run_id": run_id})),
        run,
        "model-v1",
        3600,
    )
    assert ok is True
    run.assert_called_once_with(user_ids=["user-a"], model_version="model-v1", run_id=run_id)
    sqs.delete_message.assert_called_once()

    sqs.reset_mock()
    run.side_effect = RuntimeError("temporary inference failure")
    ok = process_message(
        sqs,
        "https://sqs.example/queue",
        _message(json.dumps({"user_id": "user-a", "run_id": run_id})),
        run,
        "model-v1",
        3600,
    )
    assert ok is False
    sqs.delete_message.assert_not_called()


def test_bad_message_is_left_for_sqs_retry_and_dead_letter_redrive():
    sqs = Mock()
    run = Mock()
    ok = process_message(sqs, "queue-url", _message("{"), run, "model-v1", 3600)
    assert ok is False
    run.assert_not_called()
    sqs.delete_message.assert_not_called()
