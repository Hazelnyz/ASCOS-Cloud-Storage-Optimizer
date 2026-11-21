"""
Tests for frequently-used-fn handler.

Tests the BatchGetItem logic for fetching top_reasons from the base table
after the GSI query, including retry logic, fail-open behavior, and
edge cases.
"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "frequently-used-fn"))
import handler


@pytest.fixture(autouse=True)
def setup_env_and_reset_cache():
    """Set dummy env vars and reset cached DynamoDB resources before each test."""
    os.environ["PREDICTIONS_TABLE"] = "test-predictions-table"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    handler._reset_cache()
    yield
    handler._reset_cache()


def test_fetch_top_reasons_batch_returns_reasons():
    """BatchGetItem should return top_reasons for valid prediction_ids."""
    mock_client = MagicMock()
    mock_client.batch_get_item.return_value = {
        "Responses": {
            "test-predictions-table": [
                {
                    "prediction_id": {"S": "pred1"},
                    "top_reasons": {
                        "L": [
                            {
                                "M": {
                                    "feature": {"S": "file_type"},
                                    "contribution": {"S": "+0.5000"},
                                    "direction": {"S": "positive"}
                                }
                            }
                        ]
                    }
                }
            ]
        },
        "UnprocessedKeys": {}
    }

    with patch.object(handler, "_get_client", return_value=mock_client):
        result = handler._fetch_top_reasons_batch(["pred1"])
    
    assert result == {
        "pred1": [
            {"feature": "file_type", "contribution": "+0.5000", "direction": "positive"}
        ]
    }


def test_fetch_top_reasons_batch_empty_list_for_missing():
    """Missing top_reasons should return empty list."""
    mock_client = MagicMock()
    mock_client.batch_get_item.return_value = {
        "Responses": {
            "test-predictions-table": [
                {
                    "prediction_id": {"S": "pred1"},
                    # No top_reasons attribute
                }
            ]
        },
        "UnprocessedKeys": {}
    }

    with patch.object(handler, "_get_client", return_value=mock_client):
        result = handler._fetch_top_reasons_batch(["pred1"])
    
    assert result == {"pred1": []}


def test_fetch_top_reasons_batch_empty_input():
    """Empty prediction_ids list should return empty dict."""
    result = handler._fetch_top_reasons_batch([])
    assert result == {}


def test_fetch_top_reasons_batch_unprocessed_keys_retry():
    """UnprocessedKeys should trigger retry with backoff."""
    mock_client = MagicMock()
    # First call returns unprocessed keys, second call succeeds
    mock_client.batch_get_item.side_effect = [
        {
            "Responses": {"test-predictions-table": []},
            "UnprocessedKeys": {
                "test-predictions-table": {
                    "Keys": [{"prediction_id": {"S": "pred1"}}]
                }
            }
        },
        {
            "Responses": {
                "test-predictions-table": [
                    {
                        "prediction_id": {"S": "pred1"},
                        "top_reasons": {"L": []}
                    }
                ]
            },
            "UnprocessedKeys": {}
        }
    ]

    with patch.object(handler, "_get_client", return_value=mock_client):
        with patch("time.sleep"):  # Mock sleep to avoid delay
            result = handler._fetch_top_reasons_batch(["pred1"])
    
    assert result == {"pred1": []}
    assert mock_client.batch_get_item.call_count == 2


def test_fetch_top_reasons_batch_client_error_fails_open():
    """ClientError should fail open with empty top_reasons and return 200."""
    from botocore.exceptions import ClientError
    
    mock_client = MagicMock()
    mock_client.batch_get_item.side_effect = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException"}},
        "BatchGetItem"
    )

    with patch.object(handler, "_get_client", return_value=mock_client):
        result = handler._fetch_top_reasons_batch(["pred1", "pred2"])
    
    # Fail open: return empty list for all prediction_ids
    assert result == {"pred1": [], "pred2": []}


def test_fetch_top_reasons_batch_unprocessed_keys_max_retries():
    """After max retries, remaining unprocessed keys should fail open."""
    mock_client = MagicMock()
    # Always return unprocessed keys
    mock_client.batch_get_item.return_value = {
        "Responses": {"test-predictions-table": []},
        "UnprocessedKeys": {
            "test-predictions-table": {
                "Keys": [{"prediction_id": {"S": "pred1"}}]
            }
        }
    }

    with patch.object(handler, "_get_client", return_value=mock_client):
        with patch("time.sleep"):
            result = handler._fetch_top_reasons_batch(["pred1"])
    
    # After max retries, fail open for unprocessed keys
    assert result == {"pred1": []}
    assert mock_client.batch_get_item.call_count == handler.BATCH_GET_MAX_RETRIES


def test_handler_includes_top_reasons_in_response():
    """Handler should include top_reasons in API response."""
    mock_table = MagicMock()
    mock_table.query.return_value = {
        "Items": [
            {
                "file_id": "file1",
                "p_access": 0.7,
                "candidate_tiers": ["HOT"],
                "bandit_choice": "HOT",
                "prediction_timestamp": "2024-01-01T00:00:00Z",
                "prediction_id": "pred1"
            }
        ]
    }

    mock_client = MagicMock()
    mock_client.batch_get_item.return_value = {
        "Responses": {
            "test-predictions-table": [
                {
                    "prediction_id": {"S": "pred1"},
                    "top_reasons": {
                        "L": [
                            {
                                "M": {
                                    "feature": {"S": "file_age_days"},
                                    "contribution": {"S": "+0.3000"},
                                    "direction": {"S": "positive"}
                                }
                            }
                        ]
                    }
                }
            ]
        },
        "UnprocessedKeys": {}
    }

    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": "user123"
                    }
                }
            }
        }
    }

    with patch.object(handler, "_get_table", return_value=mock_table):
        with patch.object(handler, "_get_client", return_value=mock_client):
            response = handler.handler(event, None)
    
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert len(body["predictions"]) == 1
    assert body["predictions"][0]["topReasons"] == [
        {"feature": "file_age_days", "contribution": "+0.3000", "direction": "positive"}
    ]


def test_handler_batch_get_failure_returns_200_with_empty_reasons():
    """Handler should return 200 with empty top_reasons if BatchGetItem fails."""
    from botocore.exceptions import ClientError
    
    mock_table = MagicMock()
    mock_table.query.return_value = {
        "Items": [
            {
                "file_id": "file1",
                "p_access": 0.7,
                "candidate_tiers": ["HOT"],
                "bandit_choice": "HOT",
                "prediction_timestamp": "2024-01-01T00:00:00Z",
                "prediction_id": "pred1"
            }
        ]
    }

    mock_client = MagicMock()
    mock_client.batch_get_item.side_effect = ClientError(
        {"Error": {"Code": "InternalServerError"}},
        "BatchGetItem"
    )

    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": "user123"
                    }
                }
            }
        }
    }

    with patch.object(handler, "_get_table", return_value=mock_table):
        with patch.object(handler, "_get_client", return_value=mock_client):
            response = handler.handler(event, None)
    
    body = json.loads(response["body"])
    # Should still return 200 (fail open)
    assert response["statusCode"] == 200
    assert len(body["predictions"]) == 1
    # top_reasons should be empty due to BatchGetItem failure
    assert body["predictions"][0]["topReasons"] == []


def test_handler_existing_gsi_query_still_works():
    """Existing GSI query logic Should still work without BatchGetItem changes."""
    mock_table = MagicMock()
    mock_table.query.return_value = {
        "Items": [
            {
                "file_id": "file1",
                "p_access": 0.7,
                "candidate_tiers": ["HOT"],
                "bandit_choice": "HOT",
                "prediction_timestamp": "2024-01-01T00:00:00Z",
                "prediction_id": "pred1"
            }
        ]
    }

    mock_client = MagicMock()
    mock_client.batch_get_item.return_value = {
        "Responses": {
            "test-predictions-table": [
                {
                    "prediction_id": {"S": "pred1"},
                    "top_reasons": {"L": []}
                }
            ]
        },
        "UnprocessedKeys": {}
    }

    event = {
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": "user123"
                    }
                }
            }
        }
    }

    with patch.object(handler, "_get_table", return_value=mock_table):
        with patch.object(handler, "_get_client", return_value=mock_client):
            response = handler.handler(event, None)
    
    # Verify GSI query was called with correct parameters
    mock_table.query.assert_called_once()
    call_kwargs = mock_table.query.call_args[1]
    assert call_kwargs["IndexName"] == "user-index"
    assert call_kwargs["ScanIndexForward"] is False
    assert call_kwargs["Limit"] == handler.RESULT_LIMIT
    
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert len(body["predictions"]) == 1
