"""
PolyDev Coach — AWS Bedrock / Amazon Nova Client
Amazon Nova client implementation for the hackathon submission.

Nova model IDs used:
  Analyzer  → amazon.nova-micro-v1:0   (fast, cheap, structured JSON output)
  Coach     → amazon.nova-lite-v1:0    (RAG + reasoning, better context window)
  Refactor  → amazon.nova-pro-v1:0     (strongest code generation)
  Validator → amazon.nova-lite-v1:0    (reasoning + scoring)
  Optimizer → amazon.nova-micro-v1:0   (light formatting pass)

Pricing reference (us-east-1, on-demand, per 1M tokens):
  Nova Micro : $0.035 input  / $0.140 output
  Nova Lite  : $0.060 input  / $0.240 output
  Nova Pro   : $0.800 input  / $3.200 output

Cost per review (estimated ~8K tokens total):
  Micro calls  : ~$0.001
  Lite calls   : ~$0.002
  Pro call     : ~$0.015
  TOTAL / review ≈ $0.018  (well under $0.02 per analysis)
"""

import json
import logging
import re
from typing import Any, Dict

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from config import settings

logger = logging.getLogger(__name__)

# ─── Model IDs ────────────────────────────────────────────────────────────────
# These are the canonical Bedrock model IDs for the Nova family.
# Nova 2 variants are available where listed; fall back to v1 if not enabled.
NOVA_MICRO  = "amazon.nova-micro-v1:0"
NOVA_LITE   = "amazon.nova-lite-v1:0"
NOVA_PRO    = "amazon.nova-pro-v1:0"

# Agent → model mapping (cost-aware routing)
AGENT_MODEL_MAP = {
    "analyzer":  NOVA_MICRO,   # Structured JSON, static enrichment — cheapest
    "coach":     NOVA_LITE,    # RAG + explanation — needs reasoning
    "refactor":  NOVA_PRO,     # Code generation — needs strongest model
    "validator": NOVA_LITE,    # Scoring + logic check — mid tier
    "optimizer": NOVA_MICRO,   # Formatting pass — cheapest
}

# ─── Bedrock client (singleton) ───────────────────────────────────────────────
_bedrock_runtime = None

def _get_client():
    global _bedrock_runtime
    if _bedrock_runtime is None:
        config = Config(
            region_name=settings.aws_region,
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=120,
        )
        _bedrock_runtime = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=config,
        )
    return _bedrock_runtime


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _build_nova_body(system_prompt: str, user_message: str, max_tokens: int = 2048) -> dict:
    """
    Build the request body for Amazon Nova converse API.
    Nova uses the Messages API format (same as Anthropic Claude on Bedrock).
    Docs: https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-nova.html
    """
    return {
        "system": [{"text": system_prompt}],
        "messages": [
            {"role": "user", "content": [{"text": user_message}]}
        ],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": 0.1,   # Low temperature — we want deterministic JSON
            "topP": 0.9,
        },
    }


# ─── Public API ───────────────────────────────────────────────────────────────

async def call_nova_agent(
    agent_role: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 2048,
) -> Dict[str, Any]:
    """
    Call an Amazon Nova model via Bedrock Converse API and return parsed JSON.

    agent_role determines which Nova model tier is used (cost-aware routing).
    Raises ValueError if the model does not return valid JSON.
    """
    model_id = AGENT_MODEL_MAP.get(agent_role, NOVA_LITE)
    client = _get_client()

    body = _build_nova_body(system_prompt, user_message, max_tokens)

    logger.debug("Calling Nova | role=%s | model=%s | tokens_budget=%d",
                 agent_role, model_id, max_tokens)

    try:
        response = client.converse(
            modelId=model_id,
            system=body["system"],
            messages=body["messages"],
            inferenceConfig=body["inferenceConfig"],
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error("Bedrock ClientError for role=%s model=%s: %s %s",
                     agent_role, model_id, error_code, exc)
        raise

    # Extract text from converse response
    try:
        content_blocks = response["output"]["message"]["content"]
        text = " ".join(
            block["text"] for block in content_blocks if "text" in block
        )
    except (KeyError, TypeError) as exc:
        logger.error("Unexpected Bedrock response shape: %s", response)
        raise ValueError(f"Unexpected Bedrock response: {response}") from exc

    # Log token usage for cost monitoring
    usage = response.get("usage", {})
    logger.info(
        "Nova usage | role=%s | model=%s | input_tokens=%d | output_tokens=%d",
        agent_role, model_id,
        usage.get("inputTokens", 0),
        usage.get("outputTokens", 0),
    )

    # Parse JSON
    clean = _strip_markdown_fences(text)
    try:
        return json.loads(clean)
    except json.JSONDecodeError as exc:
        logger.error("Nova %s returned non-JSON:\n%s", agent_role, text[:400])
        raise ValueError(
            f"Nova agent '{agent_role}' did not return valid JSON. "
            f"Raw (truncated): {text[:300]}"
        ) from exc


async def call_nova_rag(
    knowledge_base_id: str,
    query: str,
    model_id: str = NOVA_LITE,
) -> str:
    """
    Query an Amazon Bedrock Knowledge Base with RAG.
    Used by the Coach agent to ground its explanations in domain docs.

    Returns the generated text answer (with source citations stripped).
    Docs: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html
    """
    agent_runtime = boto3.client(
        "bedrock-agent-runtime",
        region_name=settings.aws_region,
    )
    model_arn = f"arn:aws:bedrock:{settings.aws_region}::foundation-model/{model_id}"

    try:
        response = agent_runtime.retrieve_and_generate(
            input={"text": query},
            retrieveAndGenerateConfiguration={
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": knowledge_base_id,
                    "modelArn": model_arn,
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            "numberOfResults": 5,
                        }
                    },
                },
            },
        )
        return response["output"]["text"]
    except ClientError as exc:
        logger.warning("RAG retrieval failed: %s — falling back to base model", exc)
        return ""
