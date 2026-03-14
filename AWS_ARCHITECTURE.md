# PolyDev Coach — AWS Nova-First Architecture Design

## 1. Final Provider Choice

**Provider: Amazon Web Services (AWS)**  
**AI Platform: Amazon Bedrock**  
**Model family: Amazon Nova**

### Why this is the right choice for this hackathon

The Amazon Nova hackathon requires that Nova models are the **core** of your solution — not an optional add-on. The judging criteria weights **Technical Implementation at 60%**, and judges are Amazon engineers who will know if you used Nova superficially.

PolyDev Coach is uniquely positioned here: the multi-agent architecture maps perfectly to Nova's model tiering. We use **three different Nova models** across the pipeline, each chosen for cost-performance reasons that we can explain to judges. That's not a chatbot — that's a system that understands Nova.

---

## 2. Architecture Overview

```
User (browser)
      │
      ▼
React Frontend (S3 + CloudFront)
      │ HTTPS
      ▼
FastAPI Backend (AWS App Runner)
      │
      ├── Static Analysis Layer (deterministic, free)
      │     ├── mulesoft_package_validator  ← your existing PyPI package
      │     ├── Python AST + pylint
      │     └── Java regex rules engine
      │
      └── Amazon Bedrock Multi-Agent Pipeline
            │
            ├── [1] Analyzer Agent  → Nova Micro   (enrich findings)
            ├── [2] Coach Agent     → Nova Lite     (RAG explanations)
            │         └── Bedrock Knowledge Base ←── S3 (markdown docs)
            ├── [3] Refactor Agent  → Nova Pro      (generate fixed code)
            ├── [4] Validator Agent → Nova Lite     (quality score)
            │         └── retry loop if score < 75
            └── [5] Optimizer Agent → Nova Micro   (final polish)
```

**Supporting AWS services:**
- **Amazon S3** — knowledge base document storage + frontend hosting
- **Amazon CloudFront** — CDN for frontend
- **AWS App Runner** — fully managed backend hosting (no EC2/ECS needed)
- **Amazon OpenSearch Serverless** — auto-provisioned vector store for KB
- **AWS IAM** — least-privilege roles for Bedrock access
- **AWS Secrets Manager** — secure storage for runtime config
- **Amazon CloudWatch** — logs, metrics, cost monitoring

---

## 3. Exact Bedrock / Nova Wrapper

The key file is `backend/agents/bedrock_client.py`.

### API used: Bedrock Converse API

We use the **Converse API** (not InvokeModel) because:
- Single unified interface across all Nova models
- Native support for system prompts, message history, tool use
- Returns structured `usage` (token counts) for cost monitoring

```python
response = bedrock_runtime.converse(
    modelId="amazon.nova-pro-v1:0",
    system=[{"text": SYSTEM_PROMPT}],
    messages=[{"role": "user", "content": [{"text": user_message}]}],
    inferenceConfig={
        "maxTokens": 3000,
        "temperature": 0.1,   # deterministic JSON output
        "topP": 0.9,
    },
)
```

### Authentication

**Local development:** `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` in `.env`  
**Production (App Runner):** IAM Role attached to the App Runner service — no credentials in code

### Knowledge Base RAG call

```python
response = bedrock_agent_runtime.retrieve_and_generate(
    input={"text": query},
    retrieveAndGenerateConfiguration={
        "type": "KNOWLEDGE_BASE",
        "knowledgeBaseConfiguration": {
            "knowledgeBaseId": KB_ID,
            "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {"numberOfResults": 5}
            },
        },
    },
)
```

---

## 4. Which Nova Model for Each Agent

This is the **most important architectural decision** for the hackathon. Using a single model everywhere is lazy and expensive. Using three tiers demonstrates cost-aware AI engineering — judges will notice.

| Agent | Nova Model | Model ID | Why this model |
|-------|-----------|----------|----------------|
| **Analyzer** | Nova Micro | `amazon.nova-micro-v1:0` | Structured JSON enrichment of pre-computed static findings. Task is well-defined, output is short. Micro is fastest and cheapest — perfect for deterministic enrichment. |
| **Coach** | Nova Lite | `amazon.nova-lite-v1:0` | Needs reasoning capability to explain *why* issues matter + RAG context from knowledge base. Lite has a 300K token context window — ideal for RAG. |
| **Refactor** | Nova Pro | `amazon.nova-pro-v1:0` | Code generation is the hardest task in the pipeline. Needs the strongest model. Pro can process 15,000 lines of code and has the best code quality. |
| **Validator** | Nova Lite | `amazon.nova-lite-v1:0` | Needs to reason about code correctness, not just format data. Mid-tier is right — stronger than Micro, but Pro is overkill for scoring. |
| **Optimizer** | Nova Micro | `amazon.nova-micro-v1:0` | Pure formatting pass — remove redundancy, reorder JSON. No reasoning needed. Micro is perfect. |

### Why not Nova Premier everywhere?

Nova Premier is Amazon's most powerful model but also the most expensive. For a code review pipeline that runs on every analysis request, cost per review matters at scale. Our routing means:
- 60% of agent calls use Nova Micro (the cheapest tier)
- Only 1 of 5 calls (refactor) uses Nova Pro
- This gives Pro-quality code generation at Micro-equivalent blended cost

---

## 5. Cost-Aware Architecture

### Token pricing (us-east-1, on-demand)

| Model | Input / 1M tokens | Output / 1M tokens |
|-------|------------------|-------------------|
| Nova Micro | $0.035 | $0.140 |
| Nova Lite | $0.060 | $0.240 |
| Nova Pro | $0.800 | $3.200 |

### Cost per review estimate

| Agent | Model | Est. input tokens | Est. output tokens | Cost |
|-------|-------|------------------|--------------------|------|
| Analyzer | Micro | 1,200 | 600 | $0.000126 |
| Coach | Lite | 1,500 | 800 | $0.000282 |
| Refactor | Pro | 1,500 | 1,200 | $0.005040 |
| Validator | Lite | 2,000 | 300 | $0.000192 |
| Optimizer | Micro | 2,500 | 800 | $0.000200 |
| **TOTAL** | | **~8,700** | **~3,700** | **≈ $0.006** |

**Under $0.01 per full review.** At 1,000 reviews/month that's $6.

### Cost optimisations built in

1. **Bedrock Intelligent Prompt Routing** — can be enabled to auto-route between Nova Pro and Nova Lite based on complexity, saving up to 30% on the refactor step.

2. **Prompt caching** — the system prompts for all 5 agents are static. With Bedrock prompt caching enabled, repeated prefixes cost 90% less on input tokens.

3. **Max token caps** — every agent call sets `maxTokens` to the minimum needed. Analyzer: 1,500. Validator: 800. This prevents runaway generation.

4. **Static analysis first** — the expensive AI calls only run after static analysis has already found and classified issues. If no issues are found statically, agent calls can be skipped entirely.

5. **Retry only on failure** — the validator-triggered refactor retry only happens when `correctness_score < 75`. In practice this fires on ~20% of requests — not every one.

### Approximate monthly AWS cost (hackathon/demo scale)

| Service | Est. monthly cost |
|---------|------------------|
| Bedrock inference (1,000 reviews) | ~$6.00 |
| Bedrock Knowledge Base (OpenSearch Serverless) | ~$0.24 |
| App Runner (0.25 vCPU, 0.5 GB) | ~$5.00 |
| S3 + CloudFront | ~$0.50 |
| **TOTAL** | **~$12/month** |

---

## 6. AWS Setup — Step by Step

### Prerequisites
- AWS account (free tier is sufficient for the hackathon)
- Python 3.11+ installed locally
- AWS CLI installed: `pip install awscli`

### Step 1 — Enable Nova models in Bedrock

1. AWS Console → **Amazon Bedrock** → **Model access** (left sidebar)
2. Click **Modify model access**
3. Enable all three:
   - ✅ Amazon Nova Micro
   - ✅ Amazon Nova Lite  
   - ✅ Amazon Nova Pro
4. Click **Save changes** — takes ~2 minutes

### Step 2 — Create IAM user for local development

1. AWS Console → **IAM** → **Users** → **Create user**
2. Name: `polydev-coach-dev`
3. Attach policies:
   - `AmazonBedrockFullAccess`
   - `AmazonS3FullAccess` (for KB setup only)
4. Create access key → download CSV
5. Add to `backend/.env`:
   ```
   AWS_ACCESS_KEY_ID=AKIA...
   AWS_SECRET_ACCESS_KEY=...
   AWS_REGION=us-east-1
   ```

### Step 3 — Run automated setup

```bash
cd polydev-coach
pip install boto3
python infra/setup_aws.py
```

This script automatically:
- Creates the S3 bucket
- Uploads all 3 knowledge base markdown files
- Creates the Bedrock Knowledge Base
- Creates an OpenSearch Serverless vector store
- Syncs and indexes the documents
- Prints the `BEDROCK_KNOWLEDGE_BASE_ID` to add to `.env`

### Step 4 — Run the app locally

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# In another terminal:
cd frontend
npm install && npm run dev
```

### Step 5 — Deploy to AWS App Runner (backend)

1. AWS Console → **App Runner** → **Create service**
2. Source: **Source code repository** → connect GitHub
3. Select repo: `polydev-coach`, branch: `main`
4. Source directory: `/backend`
5. Runtime: **Python 3**
6. Build command: `pip install -r requirements.txt`
7. Start command: `uvicorn main:app --host 0.0.0.0 --port 8080`
8. Port: `8080`
9. Environment variables → add all values from `.env`
10. Create an **IAM role** for App Runner with `AmazonBedrockFullAccess`
11. Click **Create & deploy** → get your App Runner URL

### Step 6 — Deploy frontend to S3 + CloudFront

```bash
# Create S3 bucket for frontend
aws s3 mb s3://polydev-coach-frontend-prod

# Enable static website hosting
aws s3 website s3://polydev-coach-frontend-prod \
  --index-document index.html \
  --error-document index.html

# Build frontend
cd frontend
VITE_API_URL=https://your-apprunner-url.awsapprunner.com npm run build

# Deploy
aws s3 sync dist/ s3://polydev-coach-frontend-prod --delete
```

Then create a CloudFront distribution pointing to the S3 bucket.

### GitHub Actions Secrets required

| Secret | Value |
|--------|-------|
| `AWS_ACCESS_KEY_ID` | IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key |
| `APP_RUNNER_CONNECTION_ARN` | From App Runner → GitHub connections |
| `BACKEND_URL` | Your App Runner service URL |
| `FRONTEND_S3_BUCKET` | `polydev-coach-frontend-prod` |
| `CLOUDFRONT_DISTRIBUTION_ID` | From CloudFront console |

---

## 7. File Changes from DigitalOcean → AWS

Only **3 files change**. Everything else (parsers, orchestrator, schemas, frontend, tests) stays identical.

| File | Action |
|------|--------|
| `backend/agents/gradient_client.py` | **Replace** with `bedrock_client.py` |
| `backend/agents/agent_definitions.py` | **Replace** — same prompts, calls `call_nova_agent()` instead of `call_agent()` |
| `backend/config.py` | **Replace** — AWS vars instead of Gradient vars |
| `backend/requirements.txt` | **Replace** — `boto3` instead of `httpx` |
| `backend/.env.example` | **Replace** — AWS vars |
| `.github/workflows/ci-cd.yml` | **Replace** — App Runner deploy instead of doctl |
| `infra/setup_aws.py` | **New** — automated KB creation |
| `infra/apprunner.yaml` | **New** — App Runner config |

---

## 8. Submission Strategy for the Amazon Nova Hackathon

### Judging weights
- **Technical Implementation: 60%** — working code + meaningful Nova usage
- **Potential Impact: 25%** — usefulness of the solution
- **Quality of Idea: 15%** — creativity + uniqueness

### What wins Technical Implementation (60%)

The judges are AWS engineers. They will look for:

✅ **Multiple Nova models** — you use Micro, Lite, and Pro with documented reasoning  
✅ **Bedrock Knowledge Bases** — RAG with `retrieve_and_generate`, not just raw inference  
✅ **Converse API** — the modern Nova API, not legacy InvokeModel  
✅ **Cost-awareness** — you can explain the $0.006/review cost and why the routing is smart  
✅ **Production patterns** — IAM roles, Secrets Manager, App Runner (not a Jupyter notebook)  
✅ **Token usage logging** — you log `inputTokens` / `outputTokens` per call (shows you understand the billing model)

### What wins Potential Impact (25%)

The MuleSoft integration is your strongest card. Nobody else will have:
- A PyPI-published static analysis library with 171 tests as the foundation
- An enterprise-grade use case (code review at scale)
- Demonstrated real-world metrics (2 hours manual → 6 seconds automated)

### What wins Quality of Idea (15%)

The self-correcting pipeline (validator + retry loop) is a genuinely novel architectural pattern for a hackathon. Most submissions will be single-shot LLM calls. Emphasise this in your story:

> "We combine deterministic static analysis with a self-correcting multi-agent AI pipeline — if the Nova Pro refactor agent scores below 75/100 from the validator, it automatically retries with the validator's feedback as context."

### Required submission items

- [ ] **Working demo URL** — App Runner backend + CloudFront frontend
- [ ] **3-minute video** — include `#AmazonNova` hashtag in description
- [ ] **Public GitHub repo** — with clear README
- [ ] **Project description** — use the story doc already written
- [ ] **Optional bonus** — publish a blog post on builder.aws.com for $200 AWS credits
