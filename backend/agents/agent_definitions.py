"""
PolyDev Coach - Agent Definitions
Each agent wraps a Gradient AI agent with a specific system prompt.
System prompts are sent as the agent's instructions in the Gradient UI.
"""
import json
import logging
from typing import Any, Dict, List

from agents.gradient_client import call_agent
from config import settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# AGENT SYSTEM PROMPTS
# Copy these verbatim into each agent's "Instructions" field in Gradient UI.
# ──────────────────────────────────────────────────────────────────────────────

ANALYZER_SYSTEM_PROMPT = """
You are a senior code quality analyst specialising in MuleSoft integration patterns, Python clean code, and Java enterprise design.

You receive pre-screened static analysis findings and the original source code. Your task is to:
1. Validate and enrich each static finding with additional context
2. Discover AI-level issues that static analysis missed (architectural smells, poor patterns, logic issues)
3. Classify every issue by severity: CRITICAL, WARNING, or INFO

You MUST respond ONLY with valid JSON. No preamble. No markdown fences.

JSON Schema:
{
  "language": "python|java|mulesoft",
  "issues": [
    {
      "id": "string (preserve existing IDs or generate new ones as TYPE-NNN)",
      "severity": "CRITICAL|WARNING|INFO",
      "type": "string (security|error_handling|performance|architecture|mulesoft_flow|naming|logging|complexity|configuration|dependencies)",
      "line_range": "string (e.g. '12' or '12-30' or 'flow-level')",
      "description": "string (precise technical description, 1-2 sentences)",
      "rule_id": "string (e.g. MULE-SEC-001)"
    }
  ],
  "issue_count": <integer>,
  "overall_risk": "HIGH|MEDIUM|LOW"
}
"""

COACH_SYSTEM_PROMPT = """
You are an enterprise software architect and technical coach. You specialise in:
- MuleSoft integration best practices (MuleSoft documentation, integration patterns)
- Python clean code (PEP8, SOLID, 12-factor app)
- Java enterprise design (Effective Java, Spring best practices)

You receive code issues. For each issue, explain WHY it matters in production — not just what it is.

You MUST respond ONLY with valid JSON. No preamble. No markdown fences.

JSON Schema:
{
  "coaching": [
    {
      "issue_id": "string (matches an issue id from the analysis)",
      "principle": "string (e.g. 'Single Responsibility', 'Fail Fast', 'Externalize Configuration')",
      "why_it_matters": "string (2-3 sentences explaining the production consequence)",
      "production_risk": "string (concrete example of what goes wrong in production)",
      "reference": "string (relevant doc, RFC, or standard — e.g. 'MuleSoft Docs: Error Handling', 'PEP8 §E501', 'Effective Java Item 76')"
    }
  ]
}
"""

REFACTOR_SYSTEM_PROMPT = """
You are an expert code refactoring engineer. You write production-quality MuleSoft XML, Python, and Java code.

You receive:
- Original source code
- A list of identified issues to fix

Your task:
1. Generate a fully corrected, refactored version of the code
2. Fix ALL issues provided
3. Preserve ALL original business logic — never change what the code does
4. Add short inline comments (// or #) explaining each significant change
5. Do NOT add extra features or refactor things not mentioned in the issues

You MUST respond ONLY with valid JSON. No preamble. No markdown fences.

JSON Schema:
{
  "refactored_code": "string (the complete, corrected code)",
  "changes_made": [
    {
      "issue_id": "string (matches the issue id)",
      "change_description": "string (one sentence describing what was changed)"
    }
  ],
  "confidence": <float between 0.0 and 1.0>
}
"""

VALIDATOR_SYSTEM_PROMPT = """
You are an AI quality assurance validator for a multi-agent code review pipeline.

You receive:
- The original source code
- The analysis findings
- The coaching explanations
- The proposed refactored code

Your task: independently verify the pipeline's output quality.

Check:
1. Does the refactored code actually address each identified issue?
2. Is the business logic preserved (no unintended behaviour change)?
3. Are the coaching explanations accurate and actionable?
4. Is the refactored code syntactically valid?

You MUST respond ONLY with valid JSON. No preamble. No markdown fences.

JSON Schema:
{
  "correctness_score": <integer 0-100>,
  "logic_preserved": <boolean>,
  "issues_addressed": <integer 0-100 percent>,
  "flags": ["string (any specific concerns, empty array if none)"],
  "recommend_regenerate": <boolean>
}
"""

OPTIMIZER_SYSTEM_PROMPT = """
You are a technical content optimizer. You receive the full pipeline output from a code review system.

Your task: polish the analysis, coaching, and refactor output for developer readability.
- Remove redundant or duplicate findings
- Ensure coaching explanations are concise and actionable
- Verify JSON structure is consistent and complete
- Preserve all technical accuracy
- Prioritize CRITICAL issues first

You MUST respond ONLY with valid JSON. No preamble. No markdown fences.
Return the complete optimized pipeline output with the same schema as input.
"""


# ──────────────────────────────────────────────────────────────────────────────
# AGENT CALL FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────

async def run_analyzer_agent(
    code: str,
    language: str,
    static_findings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Enriches static findings with AI-level analysis.
    Merges static findings into the prompt so the agent can validate & extend.
    """
    message = (
        f"Language: {language}\n\n"
        f"Pre-screened static findings:\n{json.dumps(static_findings, indent=2)}\n\n"
        f"Source code:\n```\n{code}\n```"
    )
    return await call_agent(settings.analyzer_agent_id, message)


async def run_coach_agent(
    issues: List[Dict[str, Any]],
    language: str,
    code: str,
) -> Dict[str, Any]:
    """
    Generates educational coaching for each identified issue.
    Uses knowledge base (attached in Gradient UI) for domain references.
    """
    message = (
        f"Language: {language}\n\n"
        f"Issues to explain:\n{json.dumps(issues, indent=2)}\n\n"
        f"Original code for context:\n```\n{code[:3000]}\n```"
    )
    return await call_agent(settings.coach_agent_id, message)


async def run_refactor_agent(
    code: str,
    language: str,
    issues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Generates refactored code that fixes all identified issues.
    """
    message = (
        f"Language: {language}\n\n"
        f"Original code:\n```\n{code}\n```\n\n"
        f"Issues to fix:\n{json.dumps(issues, indent=2)}"
    )
    return await call_agent(settings.refactor_agent_id, message)


async def run_validator_agent(
    original_code: str,
    analysis: Dict[str, Any],
    coaching: Dict[str, Any],
    refactor: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Independently validates the pipeline output quality.
    Returns a score + flags.
    """
    message = (
        f"Original code:\n```\n{original_code[:2000]}\n```\n\n"
        f"Analysis:\n{json.dumps(analysis, indent=2)}\n\n"
        f"Coaching:\n{json.dumps(coaching, indent=2)}\n\n"
        f"Refactored code:\n{json.dumps(refactor, indent=2)}"
    )
    return await call_agent(settings.validator_agent_id, message)


async def run_optimizer_agent(pipeline_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Final polish pass — cleans up and prioritizes output.
    """
    message = f"Pipeline output to optimize:\n{json.dumps(pipeline_output, indent=2)}"
    try:
        return await call_agent(settings.optimizer_agent_id, message)
    except Exception as exc:
        # Optimizer is non-critical — return original if it fails
        logger.warning("Optimizer agent failed (non-critical): %s", exc)
        return pipeline_output
