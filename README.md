# 🛡️ PolyDev Coach

> **Multi-Agent AI Code Review for MuleSoft, Python & Java**
> Built for the [Amazon Nova Hackathon](https://amazon-nova.devpost.com/) · Powered by Amazon Bedrock

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/react-18-61dafb.svg)](https://react.dev/)
[![Powered by Amazon Nova](https://img.shields.io/badge/powered%20by-Amazon%20Nova-FF9900.svg)](https://aws.amazon.com/bedrock/nova/)
[![AWS Bedrock](https://img.shields.io/badge/AWS-Bedrock-232F3E.svg)](https://aws.amazon.com/bedrock/)

---

## 🎯 The Problem

Enterprise developers waste hours on manual code reviews, miss security vulnerabilities, and struggle to enforce consistent best practices — especially across multi-language stacks like MuleSoft + Python + Java.

**PolyDev Coach automates this.** It runs a 6-agent AI pipeline powered by Amazon Nova that analyzes, explains, and refactors your code in seconds.

---

## ✨ What Makes This Unique

Unlike a single LLM chatbot, PolyDev Coach uses a **coordinated multi-agent system** on Amazon Bedrock where each agent is assigned the correct Nova model tier for its job — balancing intelligence and cost:

```
User Code Input
      │
      ▼
┌──────────────────────────────────────────┐
│         ORCHESTRATOR (Python)            │
│   Routes code → manages pipeline         │
└──────────────────────────────────────────┘
      │              │              │
      ▼              ▼              ▼
┌──────────┐  ┌──────────┐  ┌─────────────┐
│ STATIC   │  │    AI    │  │  KNOWLEDGE  │
│ ANALYZER │→ │ ANALYZER │  │    BASE     │
│(mulesoft │  │  AGENT   │  │(RAG via AWS │
│validator)│  │Nova Micro│  │  Bedrock)   │
└──────────┘  └──────────┘  └─────────────┘
                   │
         ┌─────────┴──────────┐
         ▼                    ▼
   ┌──────────┐         ┌──────────┐
   │  COACH   │         │ REFACTOR │
   │  AGENT   │         │  AGENT   │
   │Nova Lite │         │Nova Pro  │
   │(explains │         │(generates│
   │  WHY)    │         │fixed code│
   └──────────┘         └──────────┘
         │                    │
         └─────────┬──────────┘
                   ▼
          ┌────────────────┐
          │   VALIDATOR    │
          │    AGENT       │
          │  Nova Lite     │
          │(quality score, │
          │ retry if low)  │
          └────────────────┘
                   │
                   ▼
          ┌────────────────┐
          │   OPTIMIZER    │
          │    AGENT       │
          │  Nova Micro    │
          │(final polish)  │
          └────────────────┘
                   │
                   ▼
           Frontend UI (React)
```

### Nova Model Routing — Cost-Aware Design

| Agent | Nova Model | Why |
|-------|-----------|-----|
| Analyzer | **Nova Micro** | Structured JSON enrichment — cheapest, fastest |
| Coach | **Nova Lite** | RAG + reasoning — needs context window |
| Refactor | **Nova Pro** | Code generation — needs strongest model |
| Validator | **Nova Lite** | Scoring + logic check — mid tier |
| Optimizer | **Nova Micro** | Formatting pass — cheapest |

**Estimated cost: ~$0.006 per full review** across all 5 agents.

### The MuleSoft Advantage

For MuleSoft code, we integrate the battle-tested **[mulesoft_package_validator](https://github.com/venkat-training/mulesoft_package_validator)** — a production-grade static analysis library that detects:
- Hardcoded secrets in YAML, XML, and POM files
- Orphaned flows and unused components
- Flow naming violations
- Missing error handlers
- Dependency issues

The Amazon Nova agents then enrich these findings with contextual coaching and generate refactored XML — something no static tool can do alone.

---

## 🏗️ Architecture

| Layer | Technology |
|-------|------------|
| **AI Models** | Amazon Nova Micro, Nova Lite, Nova Pro (via Amazon Bedrock) |
| **RAG Knowledge Base** | Amazon Bedrock Knowledge Bases + S3 + OpenSearch Serverless |
| **Backend** | Python 3.11 + FastAPI |
| **Frontend** | React 18 + Vite + TailwindCSS |
| **MuleSoft Static Analysis** | mulesoft_package_validator (PyPI) |
| **Python Static Analysis** | Python AST + pylint |
| **Java Static Analysis** | Custom regex rules engine |
| **Deployment** | AWS App Runner (backend) + S3 + CloudFront (frontend) |
| **CI/CD** | GitHub Actions + aws-actions |

---

## 🚀 Quick Start (Local Development)

### Prerequisites
- Python 3.11+
- Node.js 20+
- AWS account with Amazon Bedrock access
- AWS CLI: `pip install awscli`

### 1. Clone the repository
```bash
git clone https://github.com/venkat-training/polydev-coach.git
cd polydev-coach
```

### 2. Enable Amazon Nova models in Bedrock

1. AWS Console → **Amazon Bedrock** → **Model access** (left sidebar)
2. Click **Modify model access**
3. Enable all three:
   - ✅ Amazon Nova Micro
   - ✅ Amazon Nova Lite
   - ✅ Amazon Nova Pro
4. Click **Save changes** — takes ~2 minutes

### 3. Create IAM credentials

1. AWS Console → **IAM** → **Users** → **Create user**
2. Name: `polydev-coach-dev`
3. Attach policy: `AmazonBedrockFullAccess`
4. Create access key → download CSV

### 4. Run the infrastructure setup script

This script automatically creates the S3 bucket, uploads knowledge base documents, creates the Bedrock Knowledge Base, and syncs the vector index:

```bash
pip install boto3
python infra/setup_aws.py
```

It prints your `BEDROCK_KNOWLEDGE_BASE_ID` at the end — copy it.

### 5. Configure backend
```bash
cd backend
cp .env.example .env
# Edit .env with your AWS credentials and BEDROCK_KNOWLEDGE_BASE_ID
```

### 6. Run backend
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Backend runs at: http://localhost:8000
API docs at: http://localhost:8000/docs

### 7. Run frontend
```bash
cd frontend
npm install
npm run dev
```

Frontend runs at: http://localhost:3000

### 8. (Alternative) Docker Compose
```bash
# From project root — local dev only
cp backend/.env.example backend/.env
# Fill in .env values
docker-compose up --build
```

---

## 🚢 Deploy to AWS

### Backend — AWS App Runner

1. AWS Console → **App Runner** → **Create service**
2. Source: **Source code repository** → connect GitHub
3. Select repo: `polydev-coach`, branch: `main`, source dir: `/backend`
4. Runtime: **Python 3**, build: `pip install -r requirements.txt`
5. Start: `uvicorn main:app --host 0.0.0.0 --port 8080`
6. Create an IAM role with `AmazonBedrockFullAccess` and attach to the service
7. Add environment variables (see `.env.example`)
8. Deploy → get your App Runner URL

### Frontend — S3 + CloudFront

```bash
# Build with your App Runner URL
cd frontend
VITE_API_URL=https://your-service.awsapprunner.com npm run build

# Deploy to S3
aws s3 mb s3://polydev-coach-frontend
aws s3 sync dist/ s3://polydev-coach-frontend --delete
```

Then create a CloudFront distribution pointing to the S3 bucket.

### GitHub Actions Secrets Required

Add these in **GitHub → Settings → Secrets → Actions**:

| Secret | Description |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key |
| `APP_RUNNER_CONNECTION_ARN` | From App Runner → GitHub connections |
| `BACKEND_URL` | Your App Runner service URL |
| `FRONTEND_S3_BUCKET` | S3 bucket name for frontend |
| `CLOUDFRONT_DISTRIBUTION_ID` | CloudFront distribution ID |

---

## 🧪 Running Tests

```bash
cd backend

# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=. --cov-report=html
```

---

## 📂 Project Structure

```
polydev-coach/
├── backend/
│   ├── main.py                     # FastAPI app + routes
│   ├── config.py                   # AWS environment config
│   ├── requirements.txt            # boto3 + FastAPI dependencies
│   ├── Dockerfile
│   ├── .env.example                # ← Copy to .env
│   ├── agents/
│   │   ├── bedrock_client.py       # Amazon Bedrock / Nova Converse API client
│   │   ├── agent_definitions.py    # Nova system prompts + model routing
│   │   └── orchestrator.py         # 6-agent pipeline controller
│   ├── parsers/
│   │   ├── mulesoft_parser.py      # Wraps mulesoft_package_validator
│   │   ├── python_parser.py        # AST + pylint analysis
│   │   └── java_parser.py          # Regex rules engine
│   ├── models/
│   │   └── schemas.py              # Pydantic models
│   └── tests/
│       └── test_all.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx                 # Full React application
│   │   ├── main.jsx
│   │   └── index.css
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   └── Dockerfile
├── knowledge-base/
│   ├── mulesoft-best-practices.md  # Uploaded to S3 → Bedrock Knowledge Base
│   ├── python-enterprise-patterns.md
│   └── java-clean-code.md
├── infra/
│   ├── setup_aws.py                # One-time AWS infrastructure setup script
│   └── apprunner.yaml              # AWS App Runner configuration
├── .github/
│   └── workflows/
│       └── ci-cd.yml               # GitHub Actions → App Runner + S3 deploy
├── docker-compose.yml              # Local development only
├── LICENSE
└── README.md
```

---

## 🎬 Demo Flow

**Recommended order for your hackathon video:**

1. **Show the problem** — paste the bad Python/MuleSoft code pre-loaded in the editor
2. **Click Analyze** — show the pipeline diagram with Nova model labels
3. **Findings tab** — click to expand a CRITICAL issue, show Nova coaching explanation
4. **Refactor tab** — show before/after diff (Nova Pro generated)
5. **Quality Score** — show the three score rings (Nova Lite validation)
6. **MuleSoft zip upload** — drag in a project zip, show full project validation

---

## 🔑 Key Amazon Nova & Bedrock Features Used

| Feature | How Used |
|---------|----------|
| **Amazon Nova Micro** | Analyzer + Optimizer agents — fast structured JSON, lowest cost |
| **Amazon Nova Lite** | Coach + Validator agents — RAG reasoning, 300K context window |
| **Amazon Nova Pro** | Refactor agent — strongest code generation capability |
| **Bedrock Knowledge Bases** | RAG over MuleSoft/Python/Java best-practice docs via `retrieve_and_generate` |
| **Bedrock Converse API** | Unified interface across all Nova models with token usage logging |
| **OpenSearch Serverless** | Auto-provisioned vector store for semantic KB retrieval |
| **Cost-aware routing** | Three model tiers chosen per agent — ~$0.006 per full review |

---

## 📜 License

MIT — see [LICENSE](LICENSE)

---

## 🙏 Acknowledgements

- [mulesoft_package_validator](https://github.com/venkat-training/mulesoft_package_validator) — the MuleSoft static analysis engine powering this tool
- [Amazon Bedrock](https://aws.amazon.com/bedrock/) — managed AI infrastructure
- [Amazon Nova](https://aws.amazon.com/bedrock/nova/) — the model family powering all 5 agents
- Built for the [Amazon Nova Hackathon](https://amazon-nova.devpost.com/)