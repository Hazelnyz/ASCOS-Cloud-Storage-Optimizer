# forecast-fn Implementation Plan

## Current Status
Stage 5 scaffolding only. Function returns a placeholder response.

## Purpose (Master Reference §25)
Computes storage cost, retrieval cost, transition implications, and net cost impact for a proposed tier change. Supports all logical tier-to-tier comparisons (Hot<->Warm, Hot<->Cold, Warm<->Cold), single file or batch.

## Required Data Flow

### Input Options (to be decided in Stage 6/7)
**Option A: Caller provides pre-computed context**
```json
{
  "user_id": "string",
  "file_id": "string",
  "current_tier": "HOT" | "WARM" | "COLD",
  "proposed_tier": "HOT" | "WARM" | "COLD",
  "file_size_bytes": 12345,
  "access_count_30d": 10,
  "access_count_90d": 25
}
```

**Option B: Function queries access_event itself**
```json
{
  "user_id": "string",
  "file_id": "string",
  "proposed_tier": "HOT" | "WARM" | "COLD"
}
```
Function would then:
1. Query S3 for file size
2. Query protected_files for current tier
3. Query access_event for access counts

### Output
```json
{
  "current_tier": "HOT",
  "proposed_tier": "WARM",
  "file_size_bytes": 12345,
  "storage_cost_monthly": {
    "current": 0.023,
    "proposed": 0.012,
    "savings": 0.011
  },
  "retrieval_cost_estimate": {
    "current": 0.000,
    "proposed": 0.001,
    "increase": 0.001
  },
  "transition_cost": {
    "data_transfer": 0.000,
    "request_fee": 0.004
  },
  "net_cost_impact_30d": {
    "storage_savings": 0.330,
    "retrieval_increase": 0.030,
    "transition_cost": 0.004,
    "net": 0.296
  },
  "break_even_accesses": 3
}
```

## Implementation Steps

### 1. Define Cost Constants
AWS S3 pricing (example values, should be configurable via env vars):
```python
# Storage costs per GB/month
STORAGE_COSTS = {
    "HOT": 0.023,    # Standard
    "WARM": 0.012,   # Infrequent Access
    "COLD": 0.004    # Glacier
}

# Retrieval costs per GB
RETRIEVAL_COSTS = {
    "HOT": 0.000,
    "WARM": 0.010,
    "COLD": 0.030
}

# Request costs per 1,000 requests
REQUEST_COSTS = {
    "HOT": 0.0004,
    "WARM": 0.001,
    "COLD": 0.025
}

# Data transfer costs (per GB, out of region)
DATA_TRANSFER_COST = 0.09
```

### 2. Calculate Storage Cost
```python
def calculate_storage_cost(file_size_gb: int, tier: str) -> float:
    return file_size_gb * STORAGE_COSTS[tier]
```

### 3. Estimate Retrieval Cost
Based on historical access patterns:
```python
def estimate_retrieval_cost(
    file_size_gb: int, 
    access_count: int, 
    tier: str
) -> float:
    retrieval_gb = file_size_gb * access_count
    retrieval_cost = retrieval_gb * RETRIEVAL_COSTS[tier]
    request_cost = (access_count / 1000) * REQUEST_COSTS[tier]
    return retrieval_cost + request_cost
```

### 4. Calculate Transition Cost
```python
def calculate_transition_cost(
    file_size_gb: int, 
    from_tier: str, 
    to_tier: str
) -> dict:
    # Data transfer cost for moving data
    transfer_cost = file_size_gb * DATA_TRANSFER_COST
    
    # Request cost for transition (PUT/CopyObject)
    request_cost = REQUEST_COSTS[to_tier]  # One request per file
    
    return {
        "data_transfer": transfer_cost,
        "request_fee": request_cost,
        "total": transfer_cost + request_cost
    }
```

### 5. Calculate Net Impact
```python
def calculate_net_impact(
    file_size_gb: int,
    access_count: int,
    current_tier: str,
    proposed_tier: str,
    days: int = 30
) -> dict:
    storage_current = calculate_storage_cost(file_size_gb, current_tier)
    storage_proposed = calculate_storage_cost(file_size_gb, proposed_tier)
    storage_savings = storage_current - storage_proposed
    
    retrieval_current = estimate_retrieval_cost(file_size_gb, access_count, current_tier)
    retrieval_proposed = estimate_retrieval_cost(file_size_gb, access_count, proposed_tier)
    retrieval_increase = retrieval_proposed - retrieval_current
    
    transition = calculate_transition_cost(file_size_gb, current_tier, proposed_tier)
    
    # Scale to the time horizon
    storage_savings_scaled = storage_savings * (days / 30)
    retrieval_increase_scaled = retrieval_increase * (days / 30)
    
    net = storage_savings_scaled - retrieval_increase_scaled - transition["total"]
    
    return {
        "storage_savings": storage_savings_scaled,
        "retrieval_increase": retrieval_increase_scaled,
        "transition_cost": transition["total"],
        "net": net
    }
```

### 6. Calculate Break-Even Point
```python
def calculate_break_even(
    file_size_gb: int,
    current_tier: str,
    proposed_tier: str
) -> int:
    """How many accesses before retrieval costs exceed storage savings."""
    storage_savings_per_month = (
        STORAGE_COSTS[current_tier] - STORAGE_COSTS[proposed_tier]
    ) * file_size_gb
    
    retrieval_cost_per_access = (
        file_size_gb * RETRIEVAL_COSTS[proposed_tier] +
        REQUEST_COSTS[proposed_tier] / 1000
    )
    
    if retrieval_cost_per_access == 0:
        return float('inf')
    
    return storage_savings_per_month / retrieval_cost_per_access
```

## Environment Variables Required
- `STORAGE_COST_HOT`: Storage cost per GB/month for Hot tier
- `STORAGE_COST_WARM`: Storage cost per GB/month for Warm tier
- `STORAGE_COST_COLD`: Storage cost per GB/month for Cold tier
- `RETRIEVAL_COST_WARM`: Retrieval cost per GB for Warm tier
- `RETRIEVAL_COST_COLD`: Retrieval cost per GB for Cold tier
- `REQUEST_COST_HOT`: Request cost per 1,000 for Hot tier
- `REQUEST_COST_WARM`: Request cost per 1,000 for Warm tier
- `REQUEST_COST_COLD`: Request cost per 1,000 for Cold tier
- `DATA_TRANSFER_COST`: Data transfer cost per GB

## Terraform Changes Needed
**If Option B (function queries data):**
1. Add `s3:GetObject` to forecast-fn IAM role
2. Add `protected_files:GetItem` to forecast-fn IAM role
3. Add `access_event:Query` to forecast-fn IAM role

**If Option A (caller provides context):**
No additional IAM permissions needed beyond basic logging.

## Error Handling
- Return 400 if required fields missing
- Return 400 if invalid tier specified
- Return 400 if file_size_bytes is negative
- Return 500 on calculation errors

## Testing Strategy
1. Unit tests for cost calculation functions
2. Unit tests for break-even calculation
3. Integration test with mocked AWS services (if Option B)
4. Verify all tier-to-tier transitions
5. Verify edge cases (zero file size, zero accesses)

## Open Questions
1. Should the function support batch forecasting (multiple files)?
2. Should it use actual historical access data or ML-predicted access probability?
3. Should it account for data transfer costs for regional replication?
4. Should pricing be configurable per AWS region?
