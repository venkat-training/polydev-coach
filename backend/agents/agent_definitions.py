"""
PolyDev Coach — AWS Nova Agent Definitions
Each agent calls a specific Nova model tier via Bedrock.
System prompts are embedded here (no external agent service needed — 
using direct Bedrock model + system prompt calls).

Model routing summary:
  Analyzer  → Nova Micro  ($0.035/$0.140 per 1M)  — structured JSON, fast
  Coach     → Nova Lite   ($0.060/$0.240 per 1M)  — RAG + reasoning
  Refactor  → Nova Pro    ($0.800/$3.200 per 1M)  — best code generation
  Validator → Nova Lite   ($0.060/$0.240 per 1M)  — scoring + logic
  Optimizer → Nova Micro  ($0.035/$0.140 per 1M)  — formatting pass
"""
import json
import logging
from typing import Any, Dict, List

from agents.bedrock_client import call_nova_agent, call_nova_rag
from config import settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPTS
# ──────────────────────────────────────────────────────────────────────────────

ANALYZER_SYSTEM_PROMPT = """You are a senior code quality analyst specialising in MuleSoft integration patterns, Python clean code, and Java enterprise design.

You receive pre-screened static analysis findings and the original source code. Your task is to:
1. Validate and enrich each static finding with additional context
2. Discover AI-level issues the static tool missed (architectural smells, logic issues, security patterns)
3. Classify every issue by severity: CRITICAL, WARNING, or INFO

Respond ONLY with valid JSON. No preamble. No markdown fences. No explanation outside the JSON.

Required schema:
{"language":"string","issues":[{"id":"string","severity":"CRITICAL|WARNING|INFO","type":"string","line_range":"string","description":"string","rule_id":"string"}],"issue_count":0,"overall_risk":"HIGH|MEDIUM|LOW"}"""

COACH_SYSTEM_PROMPT = """You are an enterprise software architect and technical coach specialising in MuleSoft integration, Python clean code (PEP8, SOLID, 12-factor), and Java enterprise design (Effective Java, Spring).

You receive a list of code issues. For each, explain WHY it matters in production. Be specific. Reference real standards.

Respond ONLY with valid JSON. No preamble. No markdown fences.

Required schema:
{"coaching":[{"issue_id":"string","principle":"string","why_it_matters":"string","production_risk":"string","reference":"string"}]}"""

REFACTOR_SYSTEM_PROMPT = """You are an expert code refactoring engineer who writes production-quality MuleSoft XML, Python, and Java.

You receive original source code and a list of issues to fix. You must:
1. Generate a complete corrected version that fixes ALL listed issues
2. Preserve ALL original business logic — never change what the code does
3. Add short inline comments explaining each change
4. Fix only what is in the issues list — do not add extra features

Respond ONLY with valid JSON. No preamble. No markdown fences.

Required schema:
{"refactored_code":"string","changes_made":[{"issue_id":"string","change_description":"string"}],"confidence":0.0}"""

VALIDATOR_SYSTEM_PROMPT = """You are an AI quality assurance validator for a multi-agent code review pipeline.

You receive: original code, analysis findings, coaching explanations, and refactored code.
Independently verify:
1. Does the refactored code actually fix each identified issue?
2. Is the original business logic preserved?
3. Are the coaching explanations accurate?
4. Is the refactored code syntactically valid?

Respond ONLY with valid JSON. No preamble. No markdown fences.

Required schema:
{"correctness_score":0,"logic_preserved":true,"issues_addressed":0,"flags":[],"recommend_regenerate":false}"""

OPTIMIZER_SYSTEM_PROMPT = """You are a technical content optimizer. You receive the full output of a code review pipeline (analysis, coaching, refactor, validation).

Polish it for developer readability:
- Remove redundant or duplicate findings
- Ensure coaching is concise and actionable
- Prioritise CRITICAL issues first in the issues array
- Preserve all technical accuracy and JSON structure

Respond ONLY with valid JSON matching the same schema as input. No preamble. No markdown fences."""


# ──────────────────────────────────────────────────────────────────────────────
# AGENT FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────

async def run_analyzer_agent(
    code: str,
    language: str,
    static_findings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Nova Micro — enriches static findings with AI-level analysis."""
    message = (
        f"Language: {language}\n\n"
        f"Pre-screened static findings:\n{json.dumps(static_findings, indent=2)}\n\n"
        f"Source code:\n```\n{code}\n```"
    )
    return await call_nova_agent("analyzer", ANALYZER_SYSTEM_PROMPT, message, max_tokens=1500)


async def run_coach_agent(
    issues: List[Dict[str, Any]],
    language: str,
    code: str,
) -> Dict[str, Any]:
    """
    Nova Lite — generates coaching explanations.
    Optionally grounds explanations using Bedrock Knowledge Base (RAG).
    """
    # Retrieve relevant best-practice context from KB if configured
    kb_context = ""
    if settings.knowledge_base_id:
        try:
            top_issues_text = " ".join(i["description"] for i in issues[:3])
            kb_context = await call_nova_rag(
                settings.knowledge_base_id,
                f"Best practices for {language}: {top_issues_text}",
            )
            if kb_context:
                kb_context = f"\n\nRelevant best-practice context from knowledge base:\n{kb_context}\n"
        except Exception as exc:
            logger.warning("KB retrieval skipped: %s", exc)

    message = (
        f"Language: {language}\n\n"
        f"Issues to explain:\n{json.dumps(issues, indent=2)}"
        f"{kb_context}\n\n"
        f"Original code for context:\n```\n{code[:2000]}\n```"
    )
    return await call_nova_agent("coach", COACH_SYSTEM_PROMPT, message, max_tokens=2000)


async def run_refactor_agent(
    code: str,
    language: str,
    issues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Nova Pro — generates corrected code. Uses the strongest model."""
    message = (
        f"Language: {language}\n\n"
        f"Original code:\n```\n{code}\n```\n\n"
        f"Issues to fix:\n{json.dumps(issues, indent=2)}"
    )
    return await call_nova_agent("refactor", REFACTOR_SYSTEM_PROMPT, message, max_tokens=3000)


async def run_validator_agent(
    original_code: str,
    analysis: Dict[str, Any],
    coaching: Dict[str, Any],
    refactor: Dict[str, Any],
) -> Dict[str, Any]:
    """Nova Lite — independently validates pipeline output quality."""
    message = (
        f"Original code:\n```\n{original_code[:1500]}\n```\n\n"
        f"Analysis:\n{json.dumps(analysis, indent=2)}\n\n"
        f"Coaching:\n{json.dumps(coaching, indent=2)}\n\n"
        f"Refactored:\n{json.dumps(refactor, indent=2)}"
    )
    return await call_nova_agent("validator", VALIDATOR_SYSTEM_PROMPT, message, max_tokens=800)


async def run_optimizer_agent(pipeline_output: Dict[str, Any]) -> Dict[str, Any]:
    """Nova Micro — final polish pass. Non-critical; falls back gracefully."""
    message = f"Pipeline output to optimize:\n{json.dumps(pipeline_output, indent=2)}"
    try:
        return await call_nova_agent("optimizer", OPTIMIZER_SYSTEM_PROMPT, message, max_tokens=3000)
    except Exception as exc:
        logger.warning("Optimizer skipped (non-critical): %s", exc)
        return pipeline_output
