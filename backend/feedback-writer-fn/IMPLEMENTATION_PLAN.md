# feedback-writer-fn Implementation Plan

## Current Status
Stage 5 scaffolding only. Function returns a placeholder response.

## Purpose (ML Schema §6)
Writes a feedback record whenever a user confirms or overrides a recommendation. This closes the loop between the bandit's recommendation and the user's actual response, enabling Thompson Sampling to learn from real feedback.

## Required Data Flow

### Input (from frontend/caller)
```json
{
  "prediction_id": "uuid",
  "action_taken": "confirmed" | "overridden" | "no_response",
  "actual_tier": "HOT" | "WARM" | "COLD" | null,  // The tier the user actually chose
  "user_id": "string",
  "file_id": "string"
}
```

### Output
```json
{
  "feedback_event_id": "uuid",
  "status": "success"
}
```

## Implementation Steps

### 1. Add DynamoDB GetItem Permission
- Add `predictions:GetItem` to the Lambda's IAM role in `terraform/lambda.tf`
- This is needed to retrieve the `bandit_context` from the prediction record

### 2. Retrieve Prediction Context
```python
resp = predictions_table.get_item(Key={"prediction_id": prediction_id})
prediction = resp.get("Item")
bandit_context = prediction.get("bandit_context")
bandit_choice = prediction.get("bandit_choice")
```

### 3. Map Action to Reward
```python
def action_to_reward(action_taken: str, actual_tier: str | None, bandit_choice: str | None) -> int:
    if action_taken == "confirmed":
        # User accepted the bandit's recommendation
        return 1
    elif action_taken == "overridden":
        # User chose a different tier
        return -1
    elif action_taken == "no_response":
        # No explicit user action
        return 0
    else:
        raise ValueError(f"Unknown action_taken: {action_taken}")
```

### 4. Write Feedback Record
```python
feedback_item = {
    "feedback_event_id": str(uuid.uuid4()),
    "prediction_id": prediction_id,
    "user_id": user_id,
    "file_id": file_id,
    "action_taken": action_taken,
    "actual_tier": actual_tier,
    "reward": reward,
    "bandit_context": bandit_context,
    "bandit_choice": bandit_choice,
    "feedback_timestamp": datetime.now(timezone.utc).isoformat(),
}
feedback_table.put_item(Item=feedback_item)
```

### 5. Update Bandit State
Call `bandit.update_reward()` to update the Thompson Sampling parameters:
```python
if reward != 0 and bandit_context and bandit_choice:
    bandit.update_reward(
        user_id=user_id,
        context=bandit_context,
        chosen_tier=bandit_choice,
        reward=reward
    )
```

## Environment Variables Required
- `FEEDBACK_TABLE`: DynamoDB table name for feedback records
- `PREDICTIONS_TABLE`: DynamoDB table name for predictions
- `USER_BASELINE_TABLE`: DynamoDB table name for bandit state

## Terraform Changes Needed
1. Add `predictions:GetItem` to feedback-writer-fn IAM role
2. Add `user_baseline:UpdateItem` to feedback-writer-fn IAM role (for bandit state updates)

## Error Handling
- Return 400 if `prediction_id` is missing
- Return 404 if prediction not found
- Return 400 if `action_taken` is invalid
- Return 500 on DynamoDB errors

## Testing Strategy
1. Unit tests for `action_to_reward()` mapping
2. Integration test with mocked DynamoDB
3. Verify bandit state is updated correctly for each reward value
4. Verify feedback record is written with all required fields

## Open Questions
1. Should the function validate that `actual_tier` matches `bandit_choice` when `action_taken == "confirmed"`?
2. Should we rate-limit feedback submissions per user/file?
3. Should we allow multiple feedback events for the same prediction_id?
