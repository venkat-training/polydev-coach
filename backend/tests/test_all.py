"""
PolyDev Coach - Backend Tests
Run with: pytest tests/ -v
"""
import json
import os
import sys
import pytest

# ── Ensure env vars are set before imports load config ────────────────────────
os.environ.setdefault("GRADIENT_API_KEY", "test_key")
os.environ.setdefault("ANALYZER_AGENT_ID", "test-uuid-1")
os.environ.setdefault("COACH_AGENT_ID", "test-uuid-2")
os.environ.setdefault("REFACTOR_AGENT_ID", "test-uuid-3")
os.environ.setdefault("VALIDATOR_AGENT_ID", "test-uuid-4")
os.environ.setdefault("OPTIMIZER_AGENT_ID", "test-uuid-5")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.python_parser import run_python_static_analysis, _ast_analysis
from parsers.java_parser import run_java_static_analysis
from parsers.mulesoft_parser import _normalise_findings, _severity_from_keyword


# ─── Python Parser Tests ──────────────────────────────────────────────────────

class TestPythonParser:
    def test_detects_bare_except(self):
        code = """
try:
    do_something()
except:
    pass
"""
        result = _ast_analysis(code)
        rules = [i["rule_id"] for i in result]
        assert "BARE-EXCEPT" in rules

    def test_detects_hardcoded_password(self):
        code = 'password = "super_secret_123"\n'
        result = _ast_analysis(code)
        rules = [i["rule_id"] for i in result]
        assert "HARDCODED-SECRET" in rules

    def test_detects_hardcoded_api_key(self):
        code = 'api_key = "sk-abc123xyz"\n'
        result = _ast_analysis(code)
        severities = [i["severity"] for i in result]
        assert "CRITICAL" in severities

    def test_syntax_error_detected(self):
        code = "def foo(\n  # unclosed paren"
        result = _ast_analysis(code)
        assert len(result) > 0
        assert result[0]["rule_id"] == "SYNTAX-ERROR"

    def test_clean_code_returns_no_issues(self):
        code = """
import os
import logging

logger = logging.getLogger(__name__)

def get_user(user_id: int) -> dict:
    logger.info("Fetching user %s", user_id)
    return {"id": user_id}
"""
        result = _ast_analysis(code)
        # Clean code should have no issues
        assert len(result) == 0

    def test_full_static_analysis_returns_dict(self):
        code = 'password = "test"\ntry:\n    pass\nexcept:\n    pass\n'
        result = run_python_static_analysis(code)
        assert "issues" in result
        assert "issue_count" in result
        assert "overall_risk" in result
        assert isinstance(result["issues"], list)

    def test_risk_level_high_for_critical(self):
        code = 'password = "hardcoded_secret"\n'
        result = run_python_static_analysis(code)
        assert result["overall_risk"] == "HIGH"


# ─── Java Parser Tests ────────────────────────────────────────────────────────

class TestJavaParser:
    def test_detects_empty_catch(self):
        code = """
try {
    process();
} catch (Exception e) {}
"""
        result = run_java_static_analysis(code)
        rules = [i["rule_id"] for i in result["issues"]]
        assert "JAVA-EMPTY-CATCH" in rules

    def test_detects_system_out(self):
        code = 'System.out.println("hello");\n'
        result = run_java_static_analysis(code)
        rules = [i["rule_id"] for i in result["issues"]]
        assert "JAVA-SYSOUT" in rules

    def test_detects_hardcoded_password(self):
        code = 'String password = "admin123";\n'
        result = run_java_static_analysis(code)
        rules = [i["rule_id"] for i in result["issues"]]
        assert "JAVA-HARDCODED-SECRET" in rules

    def test_detects_print_stack_trace(self):
        code = "e.printStackTrace();\n"
        result = run_java_static_analysis(code)
        rules = [i["rule_id"] for i in result["issues"]]
        assert "JAVA-PRINT-STACK" in rules

    def test_returns_correct_structure(self):
        result = run_java_static_analysis("System.out.println('x');")
        assert "issues" in result
        assert "issue_count" in result
        assert "overall_risk" in result


# ─── MuleSoft Parser Tests ────────────────────────────────────────────────────

class TestMulesoftParser:
    def test_severity_keywords_critical(self):
        assert _severity_from_keyword("hardcoded password detected") == "CRITICAL"
        assert _severity_from_keyword("API key in config") == "CRITICAL"

    def test_severity_keywords_warning(self):
        assert _severity_from_keyword("orphaned flow") == "WARNING"
        assert _severity_from_keyword("missing error handler") == "WARNING"

    def test_severity_keywords_info(self):
        assert _severity_from_keyword("flow naming convention") == "INFO"

    def test_normalise_findings_security(self):
        raw = {
            "security_warnings": [
                {"location": "config.yaml:5", "issue": "Hardcoded password detected"}
            ]
        }
        issues = _normalise_findings(raw)
        assert len(issues) == 1
        assert issues[0]["severity"] == "CRITICAL"
        assert issues[0]["type"] == "security"

    def test_normalise_findings_orphans(self):
        raw = {
            "orphan_results": {
                "orphaned_flows": ["unusedFlow", "anotherDeadFlow"]
            }
        }
        issues = _normalise_findings(raw)
        assert len(issues) == 2
        assert all(i["rule_id"] == "MULE-ORPHAN-FLOW" for i in issues)

    def test_normalise_empty_raw(self):
        issues = _normalise_findings({})
        assert issues == []


# ─── Integration: FastAPI endpoint ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoint():
    """Test health check doesn't require Gradient connection."""
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_review_endpoint_validation():
    """Test that invalid language returns 422."""
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/review",
            json={"code": "print('hello')", "language": "cobol"},  # Invalid
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_review_endpoint_empty_code():
    """Test that empty code returns 422."""
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/review",
            json={"code": "   ", "language": "python"},
        )
    assert response.status_code == 422
