"""
PolyDev Coach - MuleSoft Static Parser
Wraps the existing mulesoft_package_validator package to produce
structured findings compatible with the PolyDev pipeline.

Your existing package: https://github.com/venkat-training/mulesoft_package_validator
pip install mulesoft-package-validator
"""
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _severity_from_keyword(text: str) -> str:
    """Map mulesoft validator finding keywords to our severity scale."""
    text_lower = text.lower()
    if any(k in text_lower for k in ("secret", "password", "hardcoded", "credential", "token", "key")):
        return "CRITICAL"
    if any(k in text_lower for k in ("warning", "warn", "missing", "orphan", "unused")):
        return "WARNING"
    return "INFO"


def _normalise_findings(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert the mulesoft_package_validator result dict into our standard
    CodeIssue list format.

    The validator returns a dict with keys like:
      - flow_validation
      - security_warnings
      - orphan_results
      - dependency_results
      - config_results
    """
    issues = []
    idx = 1

    # ── Security warnings ────────────────────────────────────────────────────
    for warn in raw.get("security_warnings", []):
        location = warn.get("location", "unknown")
        desc = warn.get("issue", str(warn))
        issues.append({
            "id": f"MULE-SEC-{idx:03d}",
            "severity": "CRITICAL",
            "type": "security",
            "line_range": location,
            "description": desc,
            "rule_id": "MULE-SECURITY",
        })
        idx += 1

    # ── Flow validation results ───────────────────────────────────────────────
    flow_data = raw.get("flow_validation", {})
    for check_name, result in flow_data.items():
        if isinstance(result, dict) and result.get("status") in ("WARN", "ERROR", "FAIL"):
            issues.append({
                "id": f"MULE-FLOW-{idx:03d}",
                "severity": _severity_from_keyword(result.get("message", check_name)),
                "type": "mulesoft_flow",
                "line_range": "flow-level",
                "description": result.get("message", f"Flow check failed: {check_name}"),
                "rule_id": f"MULE-FLOW-{check_name.upper().replace(' ', '_')}",
            })
            idx += 1

    # ── Orphaned components ───────────────────────────────────────────────────
    for orphan in raw.get("orphan_results", {}).get("orphaned_flows", []):
        issues.append({
            "id": f"MULE-ORPHAN-{idx:03d}",
            "severity": "WARNING",
            "type": "architecture",
            "line_range": "flow-level",
            "description": f"Orphaned (unreferenced) flow detected: '{orphan}'",
            "rule_id": "MULE-ORPHAN-FLOW",
        })
        idx += 1

    # ── Dependency issues ─────────────────────────────────────────────────────
    for dep in raw.get("dependency_results", {}).get("unused_dependencies", []):
        issues.append({
            "id": f"MULE-DEP-{idx:03d}",
            "severity": "INFO",
            "type": "dependencies",
            "line_range": "pom.xml",
            "description": f"Unused Maven dependency: {dep}",
            "rule_id": "MULE-UNUSED-DEP",
        })
        idx += 1

    # ── Config issues ─────────────────────────────────────────────────────────
    for cfg_issue in raw.get("config_results", {}).get("issues", []):
        issues.append({
            "id": f"MULE-CFG-{idx:03d}",
            "severity": _severity_from_keyword(str(cfg_issue)),
            "type": "configuration",
            "line_range": "config files",
            "description": str(cfg_issue),
            "rule_id": "MULE-CONFIG",
        })
        idx += 1

    return issues


def _heuristic_xml_findings(xml_content: str) -> List[Dict[str, Any]]:
    """Fallback heuristics for direct XML input when validator is unavailable or misses findings."""
    issues: List[Dict[str, Any]] = []
    idx = 1

    def add_issue(severity: str, issue_type: str, line: int, description: str, rule_id: str) -> None:
        nonlocal idx
        issues.append({
            "id": f"MULE-XML-{idx:03d}",
            "severity": severity,
            "type": issue_type,
            "line_range": str(line),
            "description": description,
            "rule_id": rule_id,
        })
        idx += 1

    for lineno, line in enumerate(xml_content.splitlines(), start=1):
        if re.search(r'password\s*=\s*"[^"#\[]+', line, re.IGNORECASE):
            add_issue("CRITICAL", "security", lineno, "Potential hardcoded database password detected in XML.", "MULE-HARDCODED-PASSWORD")
        if re.search(r'user\s*=\s*"[^"#\[]+', line, re.IGNORECASE) and "secure::" not in line:
            add_issue("WARNING", "security", lineno, "Potential hardcoded database user detected; prefer secure properties.", "MULE-HARDCODED-USER")
        if re.search(r'<logger[^>]*level\s*=\s*"DEBUG"', line, re.IGNORECASE):
            add_issue("WARNING", "logging", lineno, "DEBUG logger found in flow. Lower verbosity for production environments.", "MULE-DEBUG-LOGGER")
        if re.search(r'<db:sql>.*queryParams.*</db:sql>', line, re.IGNORECASE):
            add_issue("CRITICAL", "security", lineno, "Potential unsafe SQL construction from query params. Use parameterized queries.", "MULE-SQL-INJECTION-RISK")

    flow_names = set(re.findall(r'<flow\s+name\s*=\s*"([^"]+)"', xml_content, flags=re.IGNORECASE))
    flow_refs = set(re.findall(r'flow-ref\s+name\s*=\s*"([^"]+)"', xml_content, flags=re.IGNORECASE))
    for flow in sorted(flow_names - flow_refs):
        if flow.lower().startswith("unused") or "helper" in flow.lower() or "orphan" in flow.lower():
            add_issue("WARNING", "architecture", 1, f"Flow '{flow}' appears to be unreferenced (possible orphan flow).", "MULE-ORPHAN-FLOW")

    if "<flow" in xml_content and "error-handler" not in xml_content.lower():
        add_issue("WARNING", "error_handling", 1, "No <error-handler> block detected in MuleSoft flow definitions.", "MULE-MISSING-ERROR-HANDLER")

    return issues


def _merge_issues(primary: List[Dict[str, Any]], secondary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge issue lists while removing duplicates by key fields."""
    merged: List[Dict[str, Any]] = []
    seen = set()
    for issue in [*primary, *secondary]:
        key = (issue.get("rule_id"), issue.get("line_range"), issue.get("description"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(issue)
    return merged


# ─── Public API ───────────────────────────────────────────────────────────────

def run_static_analysis_on_xml(xml_content: str) -> Dict[str, Any]:
    """
    Run mulesoft_package_validator on a single XML flow file.
    Creates a temporary MuleSoft project structure around it.
    Returns normalised findings dict.
    """
    heuristic_issues = _heuristic_xml_findings(xml_content)
    try:
        from mule_validator import (
            validate_flows_in_package,
            validate_api_spec_and_flows,
        )
    except ImportError:
        logger.warning(
            "mulesoft-package-validator not installed. "
            "Returning empty static analysis. Run: pip install mulesoft-package-validator"
        )
        logger.warning("Falling back to heuristic MuleSoft XML analysis.")
        issues = heuristic_issues
        overall_risk = (
            "HIGH" if any(i["severity"] == "CRITICAL" for i in issues)
            else "MEDIUM" if any(i["severity"] == "WARNING" for i in issues)
            else "LOW"
        )
        return {
            "issues": issues,
            "issue_count": len(issues),
            "overall_risk": overall_risk,
            "raw_validator_output": {},
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        # Minimal MuleSoft project structure
        src_main_mule = Path(tmpdir) / "src" / "main" / "mule"
        src_main_mule.mkdir(parents=True)
        src_main_resources = Path(tmpdir) / "src" / "main" / "resources"
        src_main_resources.mkdir(parents=True)

        # Write the flow XML
        flow_file = src_main_mule / "main-flow.xml"
        flow_file.write_text(xml_content, encoding="utf-8")

        # Minimal pom.xml so dependency validator doesn't crash
        pom = Path(tmpdir) / "pom.xml"
        pom.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<project><modelVersion>4.0.0</modelVersion>
<groupId>com.example</groupId><artifactId>temp</artifactId><version>1.0.0</version>
<packaging>mule-application</packaging>
<dependencies></dependencies></project>""",
            encoding="utf-8",
        )

        try:
            flow_results = validate_flows_in_package(tmpdir)
            api_results = validate_api_spec_and_flows(tmpdir)
        except Exception as exc:
            logger.error("mulesoft_package_validator error: %s", exc)
            flow_results = {}
            api_results = {}

    raw = {**flow_results, **api_results}
    issues = _merge_issues(_normalise_findings(raw), heuristic_issues)
    overall_risk = (
        "HIGH" if any(i["severity"] == "CRITICAL" for i in issues)
        else "MEDIUM" if any(i["severity"] == "WARNING" for i in issues)
        else "LOW"
    )
    return {
        "issues": issues,
        "issue_count": len(issues),
        "overall_risk": overall_risk,
        "raw_validator_output": raw,
    }


def run_static_analysis_on_project(project_path: str) -> Dict[str, Any]:
    """
    Run full mulesoft_package_validator on an extracted MuleSoft project directory.
    Used when a user uploads a .zip of their project.
    """
    try:
        from mule_validator import (
            validate_flows_in_package,
            validate_api_spec_and_flows,
            check_orphan_flows,
        )
    except ImportError:
        logger.warning("mulesoft-package-validator not installed.")
        return {"issues": [], "issue_count": 0, "overall_risk": "LOW"}

    try:
        flow_results = validate_flows_in_package(project_path)
        api_results = validate_api_spec_and_flows(project_path)
        orphan_results = check_orphan_flows(project_path)
    except Exception as exc:
        logger.error("Validator error on project %s: %s", project_path, exc)
        flow_results = {}
        api_results = {}
        orphan_results = {}

    raw = {**flow_results, **api_results, "orphan_results": orphan_results}
    issues = _normalise_findings(raw)
    overall_risk = (
        "HIGH" if any(i["severity"] == "CRITICAL" for i in issues)
        else "MEDIUM" if any(i["severity"] == "WARNING" for i in issues)
        else "LOW"
    )
    return {
        "issues": issues,
        "issue_count": len(issues),
        "overall_risk": overall_risk,
        "raw_validator_output": raw,
    }


def extract_zip_to_temp(zip_bytes: bytes) -> Optional[str]:
    """
    Extract a zip file to a temp directory.
    Returns the path to the extracted directory, or None on failure.
    Caller is responsible for cleanup.
    """
    tmpdir = tempfile.mkdtemp(prefix="polydev_mule_")
    try:
        zip_path = os.path.join(tmpdir, "project.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_bytes)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmpdir)
        os.remove(zip_path)
        return tmpdir
    except Exception as exc:
        logger.error("Failed to extract zip: %s", exc)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None
