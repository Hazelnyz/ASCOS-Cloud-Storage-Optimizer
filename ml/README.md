# ASCOS ML — Stage 10 (in progress)

Authoritative spec: **Part 2 ("ML_SCHEMA") of the ASCOS master project
reference.** `ML_SCHEMA.md` as a standalone file no longer exists — do
not reconstruct a different one. All section references (`§1`, `§2`,
`§3`, ...) below refer to Part 2 of that combined reference document.

This directory is a merge of two prior increments ("Phase 1-3" and
"inference integration") into one package. See "Merge/cleanup note"
below for exactly what that merge did.

## Status

| Component | Spec ref | Status |
|---|---|---|
| Synthetic/reproducible access-event generator | §1 | ✅ Implemented, tested, run |
| Leakage-safe feature engineering | §2 | ✅ Implemented, tested, run |
| Label generation (7-day horizon) | §3 | ✅ Implemented, tested, run |
| Chronological split + embargo | §3 | ✅ Implemented, tested, run |
| LightGBM training (`modeling/train_lightgbm.py`) | §3/§4 | ✅ Implemented; code verified in a sandbox with no lightgbm installed (everything short of `.fit()`), then actually trained successfully in a local venv with LightGBM 4.7.0 — real model + metadata artifacts produced. Now also persists `categorical_category_maps` + `feature_schema_version` so inference can reconstruct identical category codes. |
| Evaluation metrics (`evaluation/evaluate_lightgbm.py`) | §11 | ✅ Implemented and unit-tested (54/54 tests, hand-rolled ROC-AUC/PR-AUC/etc. validated against known cases); loads the saved model and scores it — does not retrain. |
| Candidate-tier policy engine (`inference/policy.py`) | §5 Step 2/4 | ✅ Implemented — margin bands + post-bandit cost/safety downgrade |
| Protected-file hard gate (`inference/protected_gate.py`) | §5 Step 1 | ✅ Implemented — includes the Cold→immediate-restore nuance, not just freeze-in-place |
| SHAP explanations (`inference/predictor.py`) | §4 | ✅ Implemented — TreeExplainer, defensive output-shape handling (flagged as version-dependent, verify on first real run) |
| Thompson Sampling bandit (`inference/bandit.py`) | §5 Step 3 | ✅ Implemented — real Beta-Bernoulli per context, persisted to `user_baseline`, `no_response` correctly a true no-op |
| Prediction orchestration (`inference/predictor.py`, `feature_loader.py`, `batch_driver.py`) | §4/§8 | ✅ Implemented as a standalone batch entry point (`python -m ml.inference.batch_driver`) |
| **Isolation Forest anomaly detection** | §7 | ❌ **Not implemented — real gap, not deferred.** Distinct short-horizon feature set, per-user model, severity scoring all still need building. |
| **Real Lambda wiring** (`prediction-fn`, `tier-change-fn`, `feedback-writer-fn`, `training-orchestrator-fn`, `anomaly-scorer-fn`) | §33 Stage 10 | ❌ **All five are still Stage 5 scaffolds in the deployed backend.** This package is correct and real, but nothing in AWS calls it yet. Needs a Lambda packaging decision (LightGBM/SHAP are too heavy for a plain zip Lambda — almost certainly a container-image Lambda, a Terraform change) before wiring `prediction-fn`. |
| Feedback loop end-to-end | §6 | ⚠️ Half-done — `bandit.update_reward()` is correct and ready, but no Lambda calls it yet (depends on the wiring above) |
| ONNX conversion, MLflow, Evidently, federated MLP cold-start | §9/§12 | Not started — all Optimization/Recommended/Advanced tier per §12, not blocking |

Note: `pandas`/`numpy` are the only hard dependency for the Phase-1-era
rows above and for everything in `evaluate_lightgbm.py` except the
actual `booster.predict()` call — that split is deliberate (see
`train_lightgbm.py` / `evaluate_lightgbm.py` docstrings) so those parts
could be verified without lightgbm/shap installed anywhere. The
`inference/` package needs `lightgbm`, `shap`, and `boto3` (for the
DynamoDB-backed hard gate and bandit state).

## Merge/cleanup note

This package originally shipped as two separate deliverables. Merging
them was mechanical, not a rewrite — diffed every file that existed in
both before merging:
- `config.py`: one new constant added (`FEATURE_SCHEMA_VERSION`) — kept.
- `modeling/train_lightgbm.py`: small additive change (persists
  `categorical_category_maps` + `feature_schema_version` into the saved
  metadata) — kept, training behavior itself untouched.
- `inference/` (`policy.py`, `bandit.py`, `protected_gate.py`,
  `predictor.py`, `feature_loader.py`, `batch_driver.py`): new package,
  added whole.
- **Deleted**: the empty placeholder packages `ml/policy/` and
  `ml/explainability/` (both were 0-byte `__init__.py` files with no
  other content). Their real implementations already exist in
  `ml/inference/policy.py` and inline in `ml/inference/predictor.py`'s
  `top_reasons()` method. Grepped the whole merged tree for any import
  of `ml.policy` / `ml.explainability` before deleting — zero hits, so
  nothing depended on the placeholders.

## ⚠️ Synthetic data warning

Everything under `ml/data/synthetic_generator.py` produces **demo data
only** — a reproducible (seeded), invented population of users/files/
events used to develop and test the pipeline before real production
`access_event` data exists. It is not derived from, and should never be
confused with, real ASCOS user activity. Every DataFrame it returns is
tagged (`.attrs["data_source"] = "synthetic_demo_data"`) and the
generator prints/warns this on every call.

## Layout

```
ml/
├── config.py                          # spec constants (horizon, margin, ACCESS_EVENTS, etc.)
├── data/synthetic_generator.py        # §1 -- reproducible synthetic access_event log
├── features/feature_engineering.py    # §2 -- leakage-safe feature vector
├── labels/label_generation.py         # §3 -- sliding-window snapshots + 7-day-horizon label
├── splitting/chronological_split.py   # §3 -- chronological split + embargo
├── modeling/train_lightgbm.py         # §3/§4 -- LightGBM training, model artifact
├── evaluation/evaluate_lightgbm.py    # §11 -- loads saved model, scores it, never retrains
├── inference/
│   ├── policy.py                      # §5 Step 2/4 -- candidate tiers + cost/safety downgrade
│   ├── protected_gate.py              # §5 Step 1 -- hard gate, Cold->immediate-restore
│   ├── bandit.py                      # §5 Step 3 -- real Thompson Sampling, DynamoDB-persisted
│   ├── predictor.py                   # chains gate -> features -> LightGBM -> SHAP -> policy -> bandit
│   ├── feature_loader.py              # loads real feature inputs for a live prediction
│   └── batch_driver.py                # EC2/local entry point -- NOT a Lambda, NOT a second ML impl
├── models/                            # saved *.txt model + *.meta.json + *.eval.json artifacts (local only, not committed to Git)
├── run_phase1_demo.py                 # end-to-end demo of the four dependency-independent components
└── tests/
    ├── test_synthetic_generator.py
    ├── test_feature_leakage.py
    ├── test_label_generation.py
    ├── test_chronological_split.py
    └── test_evaluation_metrics.py     # hand-rolled ROC-AUC/PR-AUC/etc. validated against known cases
```

Note: `ml/inference/` currently has no dedicated test file of its own
(policy/bandit/gate logic is exercised indirectly, not yet unit-tested
the way Phase 1's four components are) — worth adding before calling
Stage 10 fully closed.

## Running

Two different environments are involved:

**This dependency-independent core** (no lightgbm/shap needed) runs
anywhere with pandas/numpy:
```bash
python3 -m unittest discover -s ml/tests -t . -v   # 54 tests total
python3 -m ml.run_phase1_demo                        # end-to-end demo
```

**Training and evaluation** need `lightgbm` installed and are run from
the project root's *parent* directory (since `ml` is the package):
```
cd F:\
.\ml\.venv\Scripts\python.exe -m ml.modeling.train_lightgbm
.\ml\.venv\Scripts\python.exe -m ml.evaluation.evaluate_lightgbm
```
`lightgbm`/`shap` are imported *lazily* inside the functions that need
them (not at module top-level), so both modules can still be imported
-- and everything in them that isn't the actual `.fit()`/`.predict()`
call can still be exercised -- in an environment with no lightgbm
installed at all. That's how the non-lightgbm parts of both modules
were verified before ever running on a machine with lightgbm present.

`pytest` is not required; tests are plain `unittest.TestCase` classes
and run with zero extra dependencies. They'll also run fine under
`pytest` later with no changes if it becomes available.

## Where things actually got executed

- The four Phase 1 components + all their tests, `train_lightgbm.py`'s
  and `evaluate_lightgbm.py`'s lightgbm-independent logic (data/feature/
  split reconstruction, categorical alignment, hand-rolled metrics) +
  their tests: verified in a sandbox with **no internet egress and no
  lightgbm/shap installed** -- confirmed by checking `pypi.org` is not
  on that environment's network allowlist.
- The actual LightGBM `.fit()` training run and (pending) the actual
  `.predict()`-based evaluation run: executed in a separate local
  Python 3.10 venv (`lightgbm==4.7.0`, `shap==0.49.1` installed via
  pip) at `F:\ml\.venv`, using the exact same code from this package.

Per explicit project decision, LightGBM/SHAP were never substituted
with an available alternative (e.g. scikit-learn's
`HistGradientBoostingClassifier`) to force something to "run" in the
sandbox that lacked them -- the spec names LightGBM and SHAP
specifically, so the real packages were used, on a machine that
actually has them, instead.
