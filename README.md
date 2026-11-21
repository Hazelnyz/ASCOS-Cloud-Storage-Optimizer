# ASCOS: Cloud Storage Optimizer

**ASCOS (Adaptive Self-Learning Cloud Storage Optimization System)** is an intelligent, automated cloud storage optimization platform that monitors S3 object usage, predicts access probabilities using Machine Learning (LightGBM + Thompson Sampling Multi-Armed Bandit), and optimizes storage costs across S3 storage tiers (Standard, Standard-IA, Glacier Instant Retrieval) with zero data loss and automated safety gates.

---

## 🚀 Key Highlights & Architecture

- **Predictive ML Tiering**: 7-day access probability prediction powered by LightGBM and real-time SHAP explainability.
- **Reinforcement Learning Feedback**: Thompson Sampling (Beta-Bernoulli bandit) that adapts per-user recommendations based on explicit and implicit feedback.
- **Safety Hard Gates**: Pinned/protected files, minimum object size thresholds, and cost-aware transition guards prevent unintended lifecycle actions or premature cold transitions.
- **Serverless Cloud Native**: 100% AWS Serverless backend (API Gateway HTTP API, AWS Lambda, DynamoDB, S3, Cognito) provisioned via Terraform.
- **Dedicated ML Worker**: Asynchronous ML inference queue (Amazon SQS) processed by an EC2 ARM64 inference worker running LightGBM and SHAP.
- **Enterprise-Grade UI**: Modern dark-theme React dashboard built with TypeScript, Vite, Tailwind CSS, Recharts, and Lucide icons.
- **Local AI Storage Assistant**: In-browser chatbot integration (Ollama / Llama 3.2:3b) to query storage stats, recommendations, and tiering tips conversationally.

---

## 📁 Repository Structure

```plaintext
ASCOS-Cloud-Storage-Optimizer/
├── backend/                  # AWS Lambda functions (Python 3.11 / Boto3)
│   ├── access-history-fn/    # S3 event logging & access trail tracking
│   ├── analytics-summary-fn/ # Storage usage aggregate metrics & breakdowns
│   ├── cost-calculator-fn/   # Live estimated S3 storage costs & savings
│   ├── file-metadata-fn/     # DynamoDB metadata CRUD & pin/protect toggles
│   ├── presigned-url-fn/     # Secure two-step S3 direct upload & download URLs
│   ├── storage-tier-fn/      # On-demand & automated S3 tier lifecycle transitions
│   └── user-preferences-fn/  # Per-user auto-tiering preferences & thresholds
├── frontend/                 # React 18 + TypeScript + Vite + Tailwind CSS
│   ├── src/
│   │   ├── components/       # Design system primitives, modals, file tables, charts
│   │   ├── pages/            # Dashboard, Files, Analytics, Predictions, Settings
│   │   ├── services/         # Typed API clients, Cognito auth, S3 upload service
│   │   └── context/          # Auth context, notifications, toast provider
├── ml/                       # Machine Learning & AI Tiering Engine
│   ├── modeling/             # LightGBM training pipelines & hyperparameter specs
│   ├── inference/            # Predictor, feature loader, bandit, & policy gates
│   ├── explainability/       # TreeExplainer & SHAP feature importance
│   ├── evaluation/           # Metrics suite (ROC-AUC, PR-AUC, calibration)
│   ├── worker/               # SQS polling inference daemon for EC2 / container
│   └── models/               # Serialized LightGBM booster artifacts & metadata
├── terraform/                # Infrastructure-as-Code (Terraform >= 1.5)
│   ├── main.tf               # Core S3 buckets, DynamoDB tables, Cognito pools
│   ├── api_gateway.tf        # HTTP API routes, stages, & CORS configurations
│   ├── lambdas.tf            # Lambda functions, IAM roles, policies, log groups
│   └── outputs.tf            # Deployed API endpoints, pool IDs, ARNs
├── docs/                     # Architecture specifications & AWS deployment logs
└── tests/                    # Backend & integration test suites
```

---

## 🛠️ Getting Started

### Prerequisites

- **Node.js**: `v18+` or `v20+` and `npm`
- **Python**: `3.11+`
- **AWS CLI**: configured with appropriate IAM credentials
- **Terraform**: `v1.5+` (for infrastructure deployments)

---

### 1. Frontend Setup

```bash
cd frontend
npm install

# Copy environment template
cp .env.example .env.local

# Fill in your deployed AWS endpoints in .env.local:
# VITE_API_ENDPOINT=https://<api-id>.execute-api.<region>.amazonaws.com
# VITE_COGNITO_USER_POOL_ID=<user-pool-id>
# VITE_COGNITO_APP_CLIENT_ID=<app-client-id>
# VITE_AWS_REGION=ap-south-1
# VITE_PREDICTIONS_ENABLED=true

npm run dev
```

The frontend dashboard will be available at `http://localhost:3000`.

---

### 2. Machine Learning Worker

The ML worker listens to SQS inference queues and scores files asynchronously:

```bash
cd ml
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run inference worker daemon
python -m ml.worker.sqs_worker
```

---

### 3. Testing Suites

- **Frontend Unit & Component Tests** (Vitest):
  ```bash
  cd frontend
  npm test
  ```
- **ML & Inference Policy Tests** (Pytest):
  ```bash
  pytest ml/tests/ -v
  ```

---

## 🛡️ License

This project is licensed under the MIT License.
