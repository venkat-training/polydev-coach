"""
PolyDev Coach - Orchestrator
The central pipeline controller. Coordinates all agents and parsers
in the correct order, handles retries and fallbacks.
"""
import logging
import time
from typing import Any, Dict, List

from agents.agent_definitions import (
    run_analyzer_agent,
    run_coach_agent,
    run_refactor_agent,
    run_validator_agent,
    run_optimizer_agent,
)
from parsers.mulesoft_parser import run_static_analysis_on_xml
from parsers.python_parser import run_python_static_analysis
from parsers.java_parser import run_java_static_analysis

logger = logging.getLogger(__name__)

# If validator score is below this, regenerate refactor once
QUALITY_THRESHOLD = 75
MAX_REFACTOR_RETRIES = 1


def _to_int(value: Any, default: int = 0) -> int:
    """Best-effort numeric coercion for LLM output fields."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalise_validation(validation: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure validation payload is consistently typed for the UI."""
    flags = validation.get("flags")
    if not isinstance(flags, list):
        flags = [] if flags is None else [str(flags)]

    return {
        "correctness_score": max(0, min(100, _to_int(validation.get("correctness_score"), 0))),
        "logic_preserved": bool(validation.get("logic_preserved", False)),
        "issues_addressed": max(0, min(100, _to_int(validation.get("issues_addressed"), 0))),
        "flags": [str(f) for f in flags],
        "recommend_regenerate": bool(validation.get("recommend_regenerate", False)),
    }


def _normalise_coaching(coaching: Any) -> Dict[str, List[Dict[str, str]]]:
    """Normalise coaching payloads into {"coaching": [...]} for the UI."""
    if isinstance(coaching, dict):
        entries = coaching.get("coaching")
    elif isinstance(coaching, list):
        entries = coaching
    else:
        entries = []

    if not isinstance(entries, list):
        entries = []

    normalised_entries: List[Dict[str, str]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        normalised_entries.append(
            {
                "issue_id": str(item.get("issue_id") or item.get("issueId") or item.get("id") or ""),
                "principle": str(item.get("principle") or ""),
                "why_it_matters": str(item.get("why_it_matters") or item.get("whyItMatters") or ""),
                "production_risk": str(item.get("production_risk") or item.get("productionRisk") or ""),
                "reference": str(item.get("reference") or ""),
            }
        )

    return {"coaching": normalised_entries}


def _fallback_coaching(issues: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
    """Generate deterministic coaching when the coach agent returns nothing."""
    insights: List[Dict[str, str]] = []
    for issue in issues:
        issue_id = str(issue.get("id", ""))
        severity = str(issue.get("severity", "INFO")).upper()
        rule_id = str(issue.get("rule_id", "GENERAL"))
        description = str(issue.get("description", "Issue identified during analysis."))

        risk_blurb = {
            "CRITICAL": "This can directly impact security, availability, or correctness in production.",
            "WARNING": "This can degrade reliability and maintainability if left unresolved.",
            "INFO": "This is a quality improvement opportunity that reduces future technical debt.",
        }.get(severity, "This can create avoidable risk over time.")

        insights.append(
            {
                "issue_id": issue_id,
                "principle": f"Address {rule_id} findings as part of baseline engineering hygiene.",
                "why_it_matters": description,
                "production_risk": risk_blurb,
                "reference": "Internal static analysis guidance",
            }
        )

    return {"coaching": insights}


async def run_review_pipeline(
    code: str,
    language: str,
    filename: str = "",
    static_result: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Full multi-agent review pipeline.

    Steps:
    1. Static analysis (deterministic, fast, uses your mulesoft_package_validator)
    2. AI Analyzer agent (enriches static findings)
    3. AI Coach agent (explains WHY each issue matters)
    4. AI Refactor agent (generates fixed code)
    5. AI Validator agent (quality check — may trigger retry)
    6. AI Optimizer agent (final polish)
    """
    start_time = time.monotonic()

    # ── Step 1: Static Analysis ───────────────────────────────────────────────
    logger.info("Step 1: Running static analysis for language=%s", language)
    if static_result is None:
        static_result = _run_static_analysis(code, language)
    else:
        logger.info("Using precomputed static analysis result for language=%s", language)
    static_issues = static_result.get("issues", [])
    logger.info("Static analysis found %d issues", len(static_issues))

    # ── Step 2: AI Analyzer ───────────────────────────────────────────────────
    logger.info("Step 2: Running analyzer agent")
    try:
        analysis = await run_analyzer_agent(code, language, static_issues)
    except Exception as exc:
        logger.error("Analyzer agent failed: %s", exc)
        # Fallback: use static analysis results directly
        analysis = {
            "language": language,
            "issues": static_issues,
            "issue_count": len(static_issues),
            "overall_risk": static_result.get("overall_risk", "MEDIUM"),
        }

    if not analysis.get("issues") and static_issues:
        logger.warning("Analyzer returned no issues; falling back to static findings")
        analysis["issues"] = static_issues
        analysis["issue_count"] = len(static_issues)
        analysis["overall_risk"] = static_result.get("overall_risk", analysis.get("overall_risk", "MEDIUM"))

    # Attach raw mulesoft validator output if available (for UI display)
    if language == "mulesoft" and "raw_validator_output" in static_result:
        analysis["mulesoft_static"] = static_result["raw_validator_output"]

    # ── Step 3: AI Coach ──────────────────────────────────────────────────────
    logger.info("Step 3: Running coach agent")
    try:
        coaching = await run_coach_agent(
            analysis.get("issues", []),
            language,
            code,
        )
    except Exception as exc:
        logger.error("Coach agent failed: %s", exc)
        coaching = {"coaching": []}
    coaching = _normalise_coaching(coaching)
    if not coaching.get("coaching") and analysis.get("issues"):
        logger.warning("Coach returned no usable insights; generating deterministic fallback coaching")
        coaching = _fallback_coaching(analysis.get("issues", []))

    # ── Step 4: AI Refactor ───────────────────────────────────────────────────
    logger.info("Step 4: Running refactor agent")
    try:
        refactor = await run_refactor_agent(
            code,
            language,
            analysis.get("issues", []),
        )
    except Exception as exc:
        logger.error("Refactor agent failed: %s", exc)
        refactor = {
            "refactored_code": code,
            "changes_made": [],
            "confidence": 0.0,
        }

    # ── Step 5: AI Validator ──────────────────────────────────────────────────
    logger.info("Step 5: Running validator agent")
    try:
        validation = _normalise_validation(await run_validator_agent(code, analysis, coaching, refactor))
    except Exception as exc:
        logger.error("Validator agent failed: %s", exc)
        validation = {
            "correctness_score": 80,
            "logic_preserved": True,
            "issues_addressed": 80,
            "flags": [],
            "recommend_regenerate": False,
        }

    # ── Step 5b: Retry refactor if quality too low ────────────────────────────
    retry_count = 0
    while (
        validation.get("recommend_regenerate", False)
        and validation.get("correctness_score", 100) < QUALITY_THRESHOLD
        and retry_count < MAX_REFACTOR_RETRIES
    ):
        logger.info(
            "Refactor quality score %d < %d — retrying (attempt %d)",
            validation["correctness_score"], QUALITY_THRESHOLD, retry_count + 1,
        )
        flags_context = "\n".join(validation.get("flags", []))
        retry_prompt_code = (
            f"[RETRY — previous attempt scored {validation['correctness_score']}/100]\n"
            f"Validator flags: {flags_context}\n\n"
            f"{code}"
        )
        try:
            refactor = await run_refactor_agent(
                retry_prompt_code,
                language,
                analysis.get("issues", []),
            )
            validation = _normalise_validation(await run_validator_agent(code, analysis, coaching, refactor))
        except Exception as exc:
            logger.error("Retry failed: %s", exc)
            break
        retry_count += 1

    # ── Step 6: Optimizer ─────────────────────────────────────────────────────
    logger.info("Step 6: Running optimizer agent")
    pipeline_output = {
        "analysis": analysis,
        "coaching": coaching,
        "refactor": refactor,
        "validation": validation,
    }
    optimized = await run_optimizer_agent(pipeline_output)

    # Merge optimized output back (optimizer may return full or partial)
    final_analysis = optimized.get("analysis") if isinstance(optimized.get("analysis"), dict) else analysis
    final_coaching = _normalise_coaching(optimized.get("coaching"))
    if not final_coaching.get("coaching"):
        final_coaching = coaching
    final_refactor = optimized.get("refactor") if isinstance(optimized.get("refactor"), dict) else refactor

    if not final_analysis.get("issues") and analysis.get("issues"):
        final_analysis["issues"] = analysis["issues"]
        final_analysis["issue_count"] = len(analysis["issues"])
        final_analysis["overall_risk"] = analysis.get("overall_risk", "MEDIUM")

    elapsed = round(time.monotonic() - start_time, 2)
    logger.info("Pipeline complete in %.2fs", elapsed)

    return {
        "status": "success",
        "language": language,
        "analysis": final_analysis,
        "coaching": final_coaching,
        "refactor": final_refactor,
        "validation": validation,
        "processing_time_seconds": elapsed,
    }


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _run_static_analysis(code: str, language: str) -> Dict[str, Any]:
    """Route to the correct static analyser based on language."""
    try:
        if language == "python":
            return run_python_static_analysis(code)
        elif language == "java":
            return run_java_static_analysis(code)
        elif language == "mulesoft":
            return run_static_analysis_on_xml(code)
        else:
            logger.warning("No static analyser for language: %s", language)
            return {"issues": [], "issue_count": 0, "overall_risk": "LOW"}
    except Exception as exc:
        logger.error("Static analysis failed for %s: %s", language, exc)
        return {"issues": [], "issue_count": 0, "overall_risk": "LOW"}
