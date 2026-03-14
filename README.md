# 🛡️ PolyDev Coach

> **Multi-Agent AI Code Review for MuleSoft, Python & Java**  
> Built for the [DigitalOcean AWS Bedrock™ AI Hackathon](https://digitalocean.devpost.com/) · Deadline: March 18, 2026

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/react-18-61dafb.svg)](https://react.dev/)
[![DigitalOcean AWS Bedrock AI](https://img.shields.io/badge/powered%20by-AWS Bedrock%20AI-0080FF.svg)](https://docs.digitalocean.com/products/AWS Bedrock-ai-platform/)

---

## 🎯 The Problem

Enterprise developers waste hours on manual code reviews, miss security vulnerabilities, and struggle to enforce consistent best practices — especially across multi-language stacks like MuleSoft + Python + Java.

**PolyDev Coach automates this.** It runs a 6-agent AI pipeline that analyzes, explains, and refactors your code in seconds.

---

## ✨ What Makes This Unique

Unlike a single LLM chatbot, PolyDev Coach uses a **coordinated multi-agent system** where each agent has a specialized role:

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
│(mulesoft │  │  AGENT   │  │(RAG via DO  │
│validator)│  │          │  │ AWS Bedrock)   │
└──────────┘  └──────────┘  └─────────────┘
                   │
         ┌─────────┴──────────┐
         ▼                    ▼
   ┌──────────┐         ┌──────────┐
   │  COACH   │         │ REFACTOR │
   │  AGENT   │         │  AGENT   │
   │(explains │         │(generates│
   │  WHY)    │         │fixed code│
   └──────────┘         └──────────┘
         │                    │
         └─────────┬──────────┘
                   ▼
          ┌────────────────┐
          │   VALIDATOR    │
          │    AGENT       │
          │(quality score, │
          │ retry if low)  │
          └────────────────┘
                   │
                   ▼
          ┌────────────────┐
          │   OPTIMIZER    │
          │    AGENT       │
          │(final polish)  │
          └────────────────┘
                   │
                   ▼
           Frontend UI (React)
```

### The MuleSoft Advantage

For MuleSoft code, we integrate the battle-tested **[mulesoft_package_validator](https://github.com/venkat-training/mulesoft_package_validator)** — a production-grade static analysis library that detects:
- Hardcoded secrets in YAML, XML, and POM files
- Orphaned flows and unused components
- Flow naming violations
- Missing error handlers
- Dependency issues

The AI agents then enrich these findings with contextual coaching and generate refactored XML — something no static tool can do alone.

---

## 🏗️ Architecture

| Layer | Technology |
|-------|------------|
| **AI Platform** | DigitalOcean AWS Bedrock AI (5 agents + knowledge bases) |
| **Backend** | Python 3.11 + FastAPI |
| **Frontend** | React 18 + Vite + TailwindCSS |
| **MuleSoft Static Analysis** | mulesoft_package_validator (PyPI) |
| **Python Static Analysis** | Python AST + pylint |
| **Java Static Analysis** | Custom regex rules engine |
| **Deployment** | DigitalOcean App Platform |
| **CI/CD** | GitHub Actions |

---

## 🚀 Quick Start (Local Development)

### Prerequisites
- Python 3.11+
- Node.js 20+
- DigitalOcean account with AWS Bedrock AI access

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/polydev-coach.git
cd polydev-coach
```

### 2. Set up AWS Bedrock AI agents

In [DigitalOcean AWS Bedrock AI Platform](https://cloud.digitalocean.com/AWS Bedrock-ai):

1. Create a **Workspace** named `polydev-coach`
2. Go to **Serverless Inference** → generate an API key
3. Create **5 Agents** with the system prompts from `backend/agents/agent_definitions.py`:
   - `PolyDev-Analyzer` — paste `ANALYZER_SYSTEM_PROMPT`
   - `PolyDev-Coach` — paste `COACH_SYSTEM_PROMPT` + attach knowledge bases
   - `PolyDev-Refactor` — paste `REFACTOR_SYSTEM_PROMPT`
   - `PolyDev-Validator` — paste `VALIDATOR_SYSTEM_PROMPT`
   - `PolyDev-Optimizer` — paste `OPTIMIZER_SYSTEM_PROMPT`
4. Create **3 Knowledge Bases** from files in `knowledge-base/`:
   - Upload `mulesoft-best-practices.md` → attach to Coach agent
   - Upload `python-enterprise-patterns.md` → attach to Coach agent
   - Upload `java-clean-code.md` → attach to Coach agent
5. Note each agent's UUID

### 3. Configure backend
```bash
cd backend
cp .env.example .env
# Edit .env with your AWS Bedrock API key and agent UUIDs
```

### 4. Run backend
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Backend runs at: http://localhost:8000  
API docs at: http://localhost:8000/docs

### 5. Run frontend
```bash
cd frontend
npm install
npm run dev
```

Frontend runs at: http://localhost:3000

### 6. (Alternative) Docker Compose
```bash
# From project root
cp backend/.env.example backend/.env
# Fill in backend/.env values
docker-compose up --build
```

---

## 🚢 Deploy to DigitalOcean App Platform

### Option A: GitHub Integration (Recommended)

1. Push this repo to GitHub (public)
2. In DigitalOcean: **Apps** → **Create App** → connect GitHub repo
3. DO auto-detects both `backend/` and `frontend/` services
4. Add environment variables from `.env.example` under **Settings → Env Vars**
5. Deploy!

### Option B: doctl CLI
```bash
# Install doctl
brew install doctl  # or snap install doctl

# Authenticate
doctl auth init

# Create app from spec
doctl apps create --spec .do/app.yaml

# Update spec later
doctl apps update <APP_ID> --spec .do/app.yaml
```

### GitHub Actions Secrets Required
Add these in **GitHub → Settings → Secrets → Actions**:

| Secret | Description |
|--------|-------------|
| `DO_ACCESS_TOKEN` | DigitalOcean personal access token |
| `DO_APP_ID` | App ID from `doctl apps list` |
| `DO_REGISTRY_NAME` | Container registry name (optional) |

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
│   ├── agents/
│   │   ├── bedrock_client.py        ← AWS Nova client
│   │   ├── agent_definitions.py     ← Nova model prompts + routing
│   │   └── orchestrator.py          ← unchanged
│   ├── parsers/
│   │   ├── mulesoft_parser.py       ← unchanged
│   │   ├── python_parser.py         ← unchanged
│   │   └── java_parser.py           ← unchanged
│   ├── models/
│   │   └── schemas.py               ← unchanged
│   ├── tests/
│   │   └── test_all.py              ← unchanged
│   ├── main.py                      ← unchanged
│   ├── config.py                    ← AWS version
│   ├── requirements.txt             ← boto3 version
│   ├── Dockerfile                   ← unchanged
│   └── .env.example                 ← AWS vars only
│
├── frontend/                        ← entirely unchanged
│   ├── src/
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile
│
├── infra/
│   ├── setup_aws.py                 ← run once to create KB
│   └── apprunner.yaml               ← App Runner config
│
├── knowledge-base/                  ← unchanged
│   ├── mulesoft-best-practices.md
│   ├── python-enterprise-patterns.md
│   └── java-clean-code.md
│
├── .github/
│   └── workflows/
│       └── ci-cd.yml                ← AWS version only
│
├── docker-compose.yml               ← unchanged (useful for local dev)
├── .gitignore                       ← unchanged
└── README.md                        ← update to AWS
```

---

## 🎬 Demo Flow

**Recommended order for your hackathon video:**

1. **Show the problem** — paste the bad Python/MuleSoft code pre-loaded in the editor
2. **Click Analyze** — show the pipeline diagram animating
3. **Findings tab** — click to expand a CRITICAL issue, show coaching explanation
4. **Refactor tab** — show before/after diff with changes list
5. **Quality Score** — show the three score rings
6. **MuleSoft zip upload** — drag in a project zip, show full project validation

---

## 🔑 Key AWS Bedrock AI Features Used

| Feature | How Used |
|---------|----------|
| **Agents** | 5 specialized agents with distinct system prompts |
| **Knowledge Bases (RAG)** | MuleSoft/Python/Java best-practice docs attached to Coach agent |
| **Serverless Inference** | Direct model access for lightweight tasks |
| **Agent Routing** | Orchestrator routes between agents based on pipeline stage |
| **Agent Evaluation** | Validator agent scores output quality with threshold-based retry |

---

## 📜 License

MIT — see [LICENSE](LICENSE)

---

## 🙏 Acknowledgements

- [mulesoft_package_validator](https://github.com/venkat-training/mulesoft_package_validator) — the MuleSoft static analysis engine powering this tool
- [DigitalOcean AWS Bedrock AI Platform](https://docs.digitalocean.com/products/AWS Bedrock-ai-platform/) — multi-agent infrastructure
- Built for the [DigitalOcean AWS Bedrock™ AI Hackathon](https://digitalocean.devpost.com/)
