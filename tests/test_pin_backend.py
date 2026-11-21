"""Unit tests for the pin/protected-state backend change (file-list-fn + file-protect-fn).

No AWS, no moto: boto3 is replaced by small in-memory fakes, so these run anywhere
(`python -m unittest tests/test_pin_backend.py`). They check the handlers' logic
(response shape, conditional write, pagination, graceful degradation) - they do NOT
prove live AWS behaviour; see the deploy checklist for the live checks.
"""
import importlib.util
import json
import os
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---- stand-ins for boto3 / botocore -------------------------------------------------
try:  # prefer the real ClientError when botocore is installed
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - stub path
    class ClientError(Exception):
        def __init__(self, error_response, operation_name):
            super().__init__(f"{operation_name}: {error_response}")
            self.response = error_response
            self.operation_name = operation_name


def client_error(code, op="Op"):
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


class FakeTable:
    def __init__(self, page_size=2):
        self.items = {}  # (user_id, file_id) -> item
        self.page_size = page_size
        self.fail_query = False
        self.fail_put = False
        self.query_users = []

    def query(self, **kw):
        if self.fail_query:
            raise client_error("ProvisionedThroughputExceededException", "Query")
        user_id = kw["KeyConditionExpression"][1]
        self.query_users.append(user_id)
        rows = sorted((v for (u, _), v in self.items.items() if u == user_id), key=lambda r: r["file_id"])
        start = 0
        if "ExclusiveStartKey" in kw:
            start = next(i for i, r in enumerate(rows) if r["file_id"] == kw["ExclusiveStartKey"]["file_id"]) + 1
        page = rows[start:start + self.page_size]
        resp = {"Items": [{k: v for k, v in r.items() if k in ("file_id", "pinned_at")} for r in page]}
        if start + self.page_size < len(rows):
            resp["LastEvaluatedKey"] = {"user_id": user_id, "file_id": page[-1]["file_id"]}
        return resp

    def put_item(self, Item, ConditionExpression=None):
        if self.fail_put:
            raise client_error("InternalServerError", "PutItem")
        k = (Item["user_id"], Item["file_id"])
        if ConditionExpression == "attribute_not_exists(file_id)" and k in self.items:
            raise client_error("ConditionalCheckFailedException", "PutItem")
        self.items[k] = dict(Item)

    def delete_item(self, Key):
        self.items.pop((Key["user_id"], Key["file_id"]), None)


class FakeS3:
    def __init__(self):
        self.objects = {}  # key -> dict(Size, LastModified, Metadata, StorageClass, ETag)
        self.copies = []
        self.fail_copy = False

    def get_paginator(self, name):
        outer = self

        class P:
            def paginate(self, Bucket, Prefix):
                import datetime as dt
                contents = [
                    {"Key": k, "Size": o["Size"], "LastModified": dt.datetime(2026, 10, 4, tzinfo=dt.timezone.utc)}
                    for k, o in sorted(outer.objects.items()) if k.startswith(Prefix)
                ]
                yield {"Contents": contents}
        return P()

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise client_error("404", "HeadObject")
        o = self.objects[Key]
        head = {"Metadata": o.get("Metadata", {}), "ETag": o.get("ETag", '"e"')}
        if o.get("StorageClass") and o["StorageClass"] != "STANDARD":
            head["StorageClass"] = o["StorageClass"]
        return head

    def copy_object(self, **kw):
        if self.fail_copy:
            raise client_error("InternalError", "CopyObject")
        self.copies.append(kw)
        self.objects[kw["Key"]]["StorageClass"] = kw["StorageClass"]


S3 = FakeS3()
TABLE = FakeTable()

fake_boto3 = types.ModuleType("boto3")
fake_boto3.client = lambda name, *a, **k: S3
fake_boto3.resource = lambda name, *a, **k: types.SimpleNamespace(Table=lambda n: TABLE)
fake_dynamodb = types.ModuleType("boto3.dynamodb")
fake_conditions = types.ModuleType("boto3.dynamodb.conditions")
fake_conditions.Key = lambda name: types.SimpleNamespace(eq=lambda v: ("eq", v))
sys.modules.update({"boto3": fake_boto3, "boto3.dynamodb": fake_dynamodb, "boto3.dynamodb.conditions": fake_conditions})
if "botocore.exceptions" not in sys.modules:
    try:
        import botocore.exceptions  # noqa: F401
    except ImportError:
        botocore = types.ModuleType("botocore")
        exc = types.ModuleType("botocore.exceptions")
        exc.ClientError = ClientError
        sys.modules.update({"botocore": botocore, "botocore.exceptions": exc})

os.environ.update({"S3_BUCKET_NAME": "test-bucket", "PROTECTED_FILES_TABLE": "test-protected"})


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


list_fn = load("list_fn", "backend/file-list-fn/handler.py")
protect_fn = load("protect_fn", "backend/file-protect-fn/handler.py")


def event(user_id, method="GET", file_id=None):
    ev = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": user_id}}}, "http": {"method": method}}}
    if file_id:
        ev["pathParameters"] = {"fileId": file_id}
    return ev


def body(resp):
    return json.loads(resp["body"])


def reset():
    S3.objects.clear()
    S3.copies.clear()
    S3.fail_copy = False
    TABLE.items.clear()
    TABLE.fail_query = False
    TABLE.fail_put = False
    TABLE.query_users.clear()


def add_file(user, fid, name="f.txt", cls="STANDARD"):
    S3.objects[f"{user}/{fid}"] = {"Size": 10, "Metadata": {"filename": name}, "StorageClass": cls}


class ListFnTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_reports_protected_and_pinned_at_per_file_across_paginated_query(self):
        for fid in ("a", "b", "c", "d", "e"):
            add_file("u1", fid)
        for fid, ts in (("a", "2026-10-01T00:00:00+00:00"), ("c", None), ("e", "2026-10-03T00:00:00+00:00")):
            TABLE.items[("u1", fid)] = {"user_id": "u1", "file_id": fid, **({"pinned_at": ts} if ts else {})}
        files = {f["fileId"]: f for f in body(list_fn.handler(event("u1"), None))["files"]}
        self.assertEqual({k: v["protected"] for k, v in files.items()}, {"a": True, "b": False, "c": True, "d": False, "e": True})
        self.assertEqual(files["a"]["pinnedAt"], "2026-10-01T00:00:00+00:00")
        self.assertIsNone(files["c"]["pinnedAt"])  # pinned before timestamps existed
        self.assertIsNone(files["b"]["pinnedAt"])
        self.assertEqual(files["e"]["pinnedAt"], "2026-10-03T00:00:00+00:00")

    def test_pin_lookup_failure_returns_files_with_unknown_state_not_an_error(self):
        add_file("u1", "a")
        TABLE.fail_query = True
        resp = list_fn.handler(event("u1"), None)
        self.assertEqual(resp["statusCode"], 200)
        f = body(resp)["files"][0]
        self.assertIsNone(f["protected"])
        self.assertIsNone(f["pinnedAt"])
        self.assertEqual(f["filename"], "f.txt")

    def test_only_the_callers_partition_is_queried_and_other_users_pins_are_ignored(self):
        add_file("u1", "a")
        TABLE.items[("u2", "a")] = {"user_id": "u2", "file_id": "a", "pinned_at": "x"}
        files = body(list_fn.handler(event("u1"), None))["files"]
        self.assertFalse(files[0]["protected"])
        self.assertEqual(set(TABLE.query_users), {"u1"})

    def test_missing_claims_is_401(self):
        self.assertEqual(list_fn.handler({}, None)["statusCode"], 401)


class ProtectFnTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_first_pin_stores_pinned_at_and_returns_it(self):
        add_file("u1", "a")
        resp = protect_fn.handler(event("u1", "POST", "a"), None)
        out = body(resp)
        self.assertEqual(resp["statusCode"], 200)
        self.assertTrue(out["protected"])
        self.assertFalse(out["tierChanged"])
        self.assertEqual(out["newTier"], "HOT")
        self.assertTrue(out["pinnedAt"])
        self.assertEqual(TABLE.items[("u1", "a")]["pinned_at"], out["pinnedAt"])
        self.assertEqual(S3.copies, [])

    def test_repin_is_idempotent_and_keeps_the_original_timestamp(self):
        add_file("u1", "a")
        TABLE.items[("u1", "a")] = {"user_id": "u1", "file_id": "a", "pinned_at": "ORIGINAL"}
        resp = protect_fn.handler(event("u1", "POST", "a"), None)
        self.assertEqual(resp["statusCode"], 200)
        self.assertTrue(body(resp)["protected"])
        self.assertIsNone(body(resp)["pinnedAt"])
        self.assertEqual(TABLE.items[("u1", "a")]["pinned_at"], "ORIGINAL")

    def test_pinning_a_cold_file_restores_it_to_hot_then_pins(self):
        add_file("u1", "a", cls="GLACIER_IR")
        out = body(protect_fn.handler(event("u1", "POST", "a"), None))
        self.assertTrue(out["tierChanged"])
        self.assertEqual(out["newTier"], "HOT")
        self.assertEqual(S3.copies[0]["StorageClass"], "STANDARD")
        self.assertEqual(S3.copies[0]["MetadataDirective"], "COPY")  # filename etc. preserved
        self.assertIn(("u1", "a"), TABLE.items)

    def test_failed_restore_writes_no_pin(self):
        add_file("u1", "a", cls="GLACIER_IR")
        S3.fail_copy = True
        resp = protect_fn.handler(event("u1", "POST", "a"), None)
        self.assertEqual(resp["statusCode"], 500)
        self.assertNotIn(("u1", "a"), TABLE.items)

    def test_put_failure_other_than_conditional_is_500(self):
        add_file("u1", "a")
        TABLE.fail_put = True
        self.assertEqual(protect_fn.handler(event("u1", "POST", "a"), None)["statusCode"], 500)

    def test_unknown_file_is_404_and_unpin_deletes_the_row(self):
        self.assertEqual(protect_fn.handler(event("u1", "POST", "nope"), None)["statusCode"], 404)
        TABLE.items[("u1", "a")] = {"user_id": "u1", "file_id": "a"}
        resp = protect_fn.handler(event("u1", "DELETE", "a"), None)
        self.assertEqual(body(resp), {"fileId": "a", "protected": False})
        self.assertNotIn(("u1", "a"), TABLE.items)


if __name__ == "__main__":
    unittest.main()
