"""
PolyDev Coach - Python Static Parser
Uses Python's built-in AST + pylint for deterministic analysis
before passing context to the AI agents.
"""
import ast
import logging
import os
import subprocess
import sys
import tempfile
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


def _run_pylint(code: str) -> List[Dict[str, Any]]:
    """Run pylint on code and return structured messages."""
    issues = []
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pylint",
                tmp_path,
                "--output-format=json",
                "--disable=C0114,C0115,C0116",  # disable docstring warnings
            ],
            capture_output=True, text=True, timeout=30
        )
        import json
        if result.stdout.strip():
            messages = json.loads(result.stdout)
            for msg in messages:
                sev_map = {"error": "CRITICAL", "warning": "WARNING", "convention": "INFO", "refactor": "INFO"}
                issues.append({
                    "id": f"PY-{msg['message-id']}",
                    "severity": sev_map.get(msg["type"], "INFO"),
                    "type": "code_quality",
                    "line_range": str(msg["line"]),
                    "description": f"[{msg['message-id']}] {msg['message']}",
                    "rule_id": msg["message-id"],
                })
    except (subprocess.TimeoutExpired, Exception) as exc:
        logger.warning("pylint run failed: %s", exc)
    finally:
        os.unlink(tmp_path)

    return issues


def _ast_analysis(code: str) -> List[Dict[str, Any]]:
    """Custom AST checks not covered by pylint."""
    issues = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [{
            "id": "PY-SYNTAX-001",
            "severity": "CRITICAL",
            "type": "syntax",
            "line_range": str(getattr(exc, "lineno", "?")),
            "description": f"Syntax error: {exc.msg}",
            "rule_id": "SYNTAX-ERROR",
        }]

    idx = 1
    for node in ast.walk(tree):
        # Bare except clauses
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            issues.append({
                "id": f"PY-AST-{idx:03d}",
                "severity": "WARNING",
                "type": "error_handling",
                "line_range": str(node.lineno),
                "description": "Bare 'except:' clause catches all exceptions including SystemExit. Use 'except Exception:'.",
                "rule_id": "BARE-EXCEPT",
            })
            idx += 1

        # Hardcoded string that looks like a secret
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name_lower = target.id.lower()
                    if any(k in name_lower for k in ("password", "secret", "api_key", "token", "passwd")):
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            issues.append({
                                "id": f"PY-AST-{idx:03d}",
                                "severity": "CRITICAL",
                                "type": "security",
                                "line_range": str(node.lineno),
                                "description": f"Hardcoded secret in variable '{target.id}'. Use environment variables.",
                                "rule_id": "HARDCODED-SECRET",
                            })
                            idx += 1

        # Functions longer than 50 lines
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            if (end - start) > 50:
                issues.append({
                    "id": f"PY-AST-{idx:03d}",
                    "severity": "WARNING",
                    "type": "complexity",
                    "line_range": f"{start}-{end}",
                    "description": f"Function '{node.name}' is {end-start} lines long. Consider splitting.",
                    "rule_id": "LONG-FUNCTION",
                })
                idx += 1

    return issues


def run_python_static_analysis(code: str) -> Dict[str, Any]:
    """
    Run combined AST + pylint analysis on Python code.
    Returns normalised findings dict.
    """
    ast_issues = _ast_analysis(code)
    pylint_issues = _run_pylint(code)

    all_issues = ast_issues + pylint_issues
    overall_risk = (
        "HIGH" if any(i["severity"] == "CRITICAL" for i in all_issues)
        else "MEDIUM" if any(i["severity"] == "WARNING" for i in all_issues)
        else "LOW"
    )
    return {
        "issues": all_issues,
        "issue_count": len(all_issues),
        "overall_risk": overall_risk,
    }
