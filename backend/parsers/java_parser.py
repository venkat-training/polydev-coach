"""
PolyDev Coach - Java Static Parser
Regex + structural analysis for Java code review.
(Tree-sitter Java parser used when available for deeper analysis.)
"""
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ─── Rule patterns ────────────────────────────────────────────────────────────

JAVA_RULES = [
    {
        "rule_id": "JAVA-CATCH-GENERIC",
        "pattern": re.compile(r"catch\s*\(\s*Exception\s+\w+\s*\)"),
        "severity": "WARNING",
        "type": "error_handling",
        "description": "Catching generic Exception. Prefer specific exception types for better error handling.",
    },
    {
        "rule_id": "JAVA-PRINT-STACK",
        "pattern": re.compile(r"\.printStackTrace\s*\(\s*\)"),
        "severity": "WARNING",
        "type": "logging",
        "description": "Using printStackTrace() instead of a proper logger (SLF4J/Log4j2).",
    },
    {
        "rule_id": "JAVA-SYSOUT",
        "pattern": re.compile(r"System\s*\.\s*out\s*\.\s*print"),
        "severity": "WARNING",
        "type": "logging",
        "description": "System.out.print* detected. Use a structured logger in production code.",
    },
    {
        "rule_id": "JAVA-HARDCODED-SECRET",
        "pattern": re.compile(
            r'(?:password|secret|apiKey|api_key|token)\s*=\s*"[^"]{3,}"',
            re.IGNORECASE,
        ),
        "severity": "CRITICAL",
        "type": "security",
        "description": "Hardcoded credential or secret detected. Use environment variables or a secrets manager.",
    },
    {
        "rule_id": "JAVA-NULL-CHECK",
        "pattern": re.compile(r"==\s*null|null\s*=="),
        "severity": "INFO",
        "type": "code_quality",
        "description": "Null check via ==. Consider using Optional<T> or Objects.requireNonNull() for clarity.",
    },
    {
        "rule_id": "JAVA-STRING-CONCAT-LOOP",
        "pattern": re.compile(r"for\s*\(.*\)\s*\{[^}]*\+=[^}]*String", re.DOTALL),
        "severity": "WARNING",
        "type": "performance",
        "description": "String concatenation in a loop. Use StringBuilder for better performance.",
    },
    {
        "rule_id": "JAVA-EMPTY-CATCH",
        "pattern": re.compile(r"catch\s*\([^)]+\)\s*\{\s*\}"),
        "severity": "CRITICAL",
        "type": "error_handling",
        "description": "Empty catch block silently swallows exceptions. Always log or rethrow.",
    },
    {
        "rule_id": "JAVA-STATIC-MUTABLE",
        "pattern": re.compile(r"private\s+static\s+(?!final)\w+\s+\w+\s*="),
        "severity": "WARNING",
        "type": "concurrency",
        "description": "Non-final static mutable field. May cause concurrency issues in multi-threaded environments.",
    },
]


def _find_line_number(code: str, match_start: int) -> str:
    """Return 1-based line number for a character offset."""
    return str(code[:match_start].count("\n") + 1)


def run_java_static_analysis(code: str) -> Dict[str, Any]:
    """
    Run regex-based static analysis on Java code.
    Returns normalised findings dict.
    """
    issues = []
    idx = 1

    for rule in JAVA_RULES:
        for match in rule["pattern"].finditer(code):
            line_no = _find_line_number(code, match.start())
            issues.append({
                "id": f"JAVA-{idx:03d}",
                "severity": rule["severity"],
                "type": rule["type"],
                "line_range": line_no,
                "description": rule["description"],
                "rule_id": rule["rule_id"],
            })
            idx += 1

    # Check method length
    method_pattern = re.compile(
        r"(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+\w+\s*\([^)]*\)\s*(?:throws[^{]+)?\{",
        re.MULTILINE,
    )
    for match in method_pattern.finditer(code):
        start_pos = match.start()
        # Count braces to find end
        brace_count = 0
        end_pos = match.end() - 1  # position of opening {
        for i, char in enumerate(code[end_pos:], start=end_pos):
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    method_lines = code[start_pos:i].count("\n")
                    if method_lines > 40:
                        issues.append({
                            "id": f"JAVA-{idx:03d}",
                            "severity": "WARNING",
                            "type": "complexity",
                            "line_range": _find_line_number(code, start_pos),
                            "description": f"Method is ~{method_lines} lines long. Consider decomposing (Single Responsibility).",
                            "rule_id": "JAVA-LONG-METHOD",
                        })
                        idx += 1
                    break

    overall_risk = (
        "HIGH" if any(i["severity"] == "CRITICAL" for i in issues)
        else "MEDIUM" if any(i["severity"] == "WARNING" for i in issues)
        else "LOW"
    )
    return {
        "issues": issues,
        "issue_count": len(issues),
        "overall_risk": overall_risk,
    }
