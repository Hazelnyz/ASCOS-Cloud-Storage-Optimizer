"""Unit tests for the upload-time stamp, forced-download header and filename decoding
(file-upload-url-fn, file-metadata-fn, file-download-url-fn, file-list-fn).

boto3 is replaced by a mock while each handler is imported, so these run anywhere with
no AWS access (`python -m unittest tests/test_upload_download_names.py`). They check
handler logic only - they do not prove live S3 behaviour.
"""
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "backend"
ENC = "r%C3%A9sum%C3%A9-%E6%B5%8B%E8%AF%95.txt"
EVENT = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "u1"}}}}, "body": json.dumps({"filename": "my report (1).pdf"})}
EV = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "u1"}}}}, "pathParameters": {"fileId": "f1"}}


def load(fn_dir):
    """Import backend/<fn_dir>/handler.py with boto3 mocked and a dummy bucket env var."""
    stub_botocore = mock.MagicMock()
    stub_botocore.exceptions.ClientError = type("ClientError", (Exception,), {})
    with mock.patch.dict(sys.modules, {"boto3": mock.MagicMock(), "botocore": stub_botocore, "botocore.exceptions": stub_botocore.exceptions}), \
            mock.patch.dict(os.environ, {"S3_BUCKET_NAME": "test-bucket", "ACCESS_EVENT_TABLE": "test-access-event"}):
        spec = importlib.util.spec_from_file_location("h_" + fn_dir.replace("-", "_"), ROOT / fn_dir / "handler.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    return m


class UploadStamp(unittest.TestCase):
    def test_signed_metadata_and_returned_headers_match(self):
        m = load("file-upload-url-fn")
        captured = {}
        m.s3 = mock.MagicMock()
        m.s3.generate_presigned_url.side_effect = lambda op, Params, ExpiresIn: captured.update(Params) or "https://s3/x"
        r = m.handler(EVENT, None); body = json.loads(r["body"])
        self.assertEqual(r["statusCode"], 200)
        md = captured["Metadata"]
        self.assertEqual(md["filename"], "my%20report%20%281%29.pdf")
        self.assertIn("uploaded-at", md)
        self.assertEqual(body["headers"], {f"x-amz-meta-{k}": v for k, v in md.items()})

    def test_requires_auth_and_filename(self):
        m = load("file-upload-url-fn")
        self.assertEqual(m.handler({}, None)["statusCode"], 401)
        ev = dict(EVENT, body="{}")
        self.assertEqual(m.handler(ev, None)["statusCode"], 400)

    def test_metadata_returns_uploaded_at(self):
        m = load("file-metadata-fn")
        from datetime import datetime, timezone
        m.s3 = mock.MagicMock()
        m.s3.head_object.return_value = {"Metadata": {"filename": "a", "uploaded-at": "2026-10-01T00:00:00+00:00"}, "ContentLength": 3, "LastModified": datetime.now(timezone.utc)}
        ev = dict(EVENT, pathParameters={"fileId": "f"})
        body = json.loads(m.handler(ev, None)["body"])
        self.assertEqual(body["uploadedAt"], "2026-10-01T00:00:00+00:00")
        m.s3.head_object.return_value = {"Metadata": {}, "ContentLength": 3}
        self.assertIsNone(json.loads(m.handler(ev, None)["body"])["uploadedAt"])


class DownloadAndNames(unittest.TestCase):
    def test_download_forces_attachment_with_real_name(self):
        m = load("file-download-url-fn"); got = {}
        m.s3 = mock.MagicMock()
        m.s3.head_object.return_value = {"Metadata": {"filename": ENC}}
        m.s3.generate_presigned_url.side_effect = lambda op, Params, ExpiresIn: got.update(Params) or "https://s3/x"
        r = m.handler(EV, None); self.assertEqual(r["statusCode"], 200)
        cd = got["ResponseContentDisposition"]
        self.assertTrue(cd.startswith("attachment;"))
        self.assertIn("filename*=UTF-8''" + ENC, cd)
        self.assertNotIn("\n", cd)
        cd.encode("ascii")  # header must be pure ASCII

    def test_download_hostile_or_missing_name(self):
        m = load("file-download-url-fn"); got = {}
        m.s3 = mock.MagicMock(); m.s3.generate_presigned_url.side_effect = lambda op, Params, ExpiresIn: got.update(Params) or "u"
        m.s3.head_object.return_value = {"Metadata": {"filename": 'a%22b%0D%0AX-Evil%3A1.txt'}}
        m.handler(EV, None); cd = got["ResponseContentDisposition"]
        self.assertNotIn("\r", cd); self.assertNotIn("\n", cd)
        self.assertEqual(cd.count('"'), 2)
        m.s3.head_object.return_value = {}
        m.handler(EV, None); self.assertIn('filename="f1"', got["ResponseContentDisposition"])

    def test_metadata_and_list_decode_names(self):
        from datetime import datetime, timezone
        m = load("file-metadata-fn"); m.s3 = mock.MagicMock()
        m.s3.head_object.return_value = {"Metadata": {"filename": ENC}, "ContentLength": 1, "LastModified": datetime.now(timezone.utc)}
        self.assertEqual(json.loads(m.handler(EV, None)["body"])["filename"], "résumé-测试.txt")
        self.assertEqual(m._decode_filename(None), None)
        self.assertEqual(m._decode_filename("plain.pdf"), "plain.pdf")



class FakeAccessTable:
    def __init__(self, pages, fail=False):
        self.pages, self.fail, self.calls = pages, fail, []

    def query(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise sys.modules["botocore.exceptions"].ClientError  # replaced below
        i = len(self.calls) - 1
        page = {"Items": self.pages[i]}
        if i + 1 < len(self.pages):
            page["LastEvaluatedKey"] = {"k": i}
        return page


def _ts(days_ago):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class AccessSummary(unittest.TestCase):
    def setUp(self):
        self.m = load("file-metadata-fn")

    def test_counts_only_window_and_reports_newest(self):
        pages = [[{"timestamp": _ts(1)}, {"timestamp": _ts(5)}], [{"timestamp": _ts(40)}, {"timestamp": _ts(50)}]]
        self.m.access_event_table = FakeAccessTable(pages)
        last, count = self.m._access_summary("u1", "f1")
        self.assertEqual(last, pages[0][0]["timestamp"])
        self.assertEqual(count, 2)
        q = self.m.access_event_table.calls[0]
        self.assertEqual(q["ExpressionAttributeValues"][":k"], "u1#f1")
        self.assertFalse(q["ScanIndexForward"])

    def test_old_only_gives_last_but_zero_recent(self):
        self.m.access_event_table = FakeAccessTable([[{"timestamp": _ts(90)}]])
        last, count = self.m._access_summary("u1", "f1")
        self.assertIsNotNone(last)
        self.assertEqual(count, 0)

    def test_never_accessed_is_zero_not_unknown(self):
        self.m.access_event_table = FakeAccessTable([[]])
        self.assertEqual(self.m._access_summary("u1", "f1"), (None, 0))

    def test_lookup_failure_is_unknown_not_zero(self):
        class Boom:
            def query(self, **kw):
                raise self_ClientError()
        self_ClientError = self.m.ClientError
        self.m.access_event_table = Boom()
        self.assertEqual(self.m._access_summary("u1", "f1"), (None, None))

    def test_zulu_cloudtrail_timestamps_parse(self):
        self.m.access_event_table = FakeAccessTable([[{"timestamp": "2020-01-01T00:00:00Z"}]])
        last, count = self.m._access_summary("u1", "f1")
        self.assertEqual((last, count), ("2020-01-01T00:00:00Z", 0))

    def test_handler_includes_fields(self):
        from datetime import datetime, timezone
        self.m.s3 = mock.MagicMock()
        self.m.s3.head_object.return_value = {"Metadata": {}, "ContentLength": 1, "LastModified": datetime.now(timezone.utc)}
        self.m.access_event_table = FakeAccessTable([[{"timestamp": _ts(2)}]])
        body = json.loads(self.m.handler(EV, None)["body"])
        self.assertEqual(body["recentAccessCount"], 1)
        self.assertEqual(body["accessWindowDays"], 30)
        self.assertIsNotNone(body["lastAccessedAt"])


if __name__ == "__main__":
    unittest.main()
