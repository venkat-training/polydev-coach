"""
PolyDev Coach — Backend Tests
Amazon Nova / AWS Bedrock variant.

Run with:
    pytest tests/ -v
    pytest tests/ --cov=. --cov-report=html

Tests cover:
  - Python AST + pylint static parser
  - Java regex static parser
  - MuleSoft validator wrapper (normalise_findings)
  - FastAPI endpoint validation (does not call Bedrock — unit tests only)
"""
import os
import sys
import io
import zipfile
import pytest

# ── Stub AWS credentials so config.py loads without real keys ─────────────────
# These are test-only values. Bedrock is never called in unit tests.
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test-key-id")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test-secret-key")
os.environ.setdefault("BEDROCK_KNOWLEDGE_BASE_ID", "test-kb-id-00000000")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.python_parser import run_python_static_analysis, _ast_analysis
from parsers.java_parser import run_java_static_analysis
from parsers.mulesoft_parser import _normalise_findings, _severity_from_keyword, _heuristic_xml_findings


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
        assert "BARE-EXCEPT" in rules, "Bare except not detected"

    def test_detects_hardcoded_password(self):
        code = 'password = "super_secret_123"\n'
        result = _ast_analysis(code)
        rules = [i["rule_id"] for i in result]
        assert "HARDCODED-SECRET" in rules, "Hardcoded password not detected"

    def test_detects_hardcoded_api_key(self):
        code = 'api_key = "sk-abc123xyz"\n'
        result = _ast_analysis(code)
        severities = [i["severity"] for i in result]
        assert "CRITICAL" in severities, "CRITICAL severity not assigned"

    def test_syntax_error_detected(self):
        code = "def foo(\n  # unclosed paren"
        result = _ast_analysis(code)
        assert len(result) > 0
        assert result[0]["rule_id"] == "SYNTAX-ERROR"

    def test_clean_code_returns_no_ast_issues(self):
        code = """
import os
import logging

logger = logging.getLogger(__name__)

def get_user(user_id: int) -> dict:
    logger.info("Fetching user %s", user_id)
    return {"id": user_id}
"""
        result = _ast_analysis(code)
        assert len(result) == 0, f"Expected no issues, got: {result}"

    def test_full_static_analysis_returns_correct_schema(self):
        code = 'password = "test"\ntry:\n    pass\nexcept:\n    pass\n'
        result = run_python_static_analysis(code)
        assert "issues" in result
        assert "issue_count" in result
        assert "overall_risk" in result
        assert isinstance(result["issues"], list)
        assert result["issue_count"] == len(result["issues"])

    def test_risk_level_high_for_critical_issue(self):
        code = 'password = "hardcoded_secret"\n'
        result = run_python_static_analysis(code)
        assert result["overall_risk"] == "HIGH"

    def test_risk_level_low_for_clean_code(self):
        code = "x = 1 + 1\n"
        result = run_python_static_analysis(code)
        assert result["overall_risk"] == "LOW"


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

    def test_returns_correct_schema(self):
        result = run_java_static_analysis("System.out.println('x');")
        assert "issues" in result
        assert "issue_count" in result
        assert "overall_risk" in result
        assert result["issue_count"] == len(result["issues"])

    def test_clean_java_returns_no_issues(self):
        code = """
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class UserService {
    private static final Logger log = LoggerFactory.getLogger(UserService.class);

    public String getUser(int id) {
        log.info("Fetching user {}", id);
        return "user-" + id;
    }
}
"""
        result = run_java_static_analysis(code)
        assert result["overall_risk"] == "LOW"


# ─── MuleSoft Parser Tests ────────────────────────────────────────────────────

class TestMulesoftParser:

    def test_severity_keywords_critical(self):
        assert _severity_from_keyword("hardcoded password detected") == "CRITICAL"
        assert _severity_from_keyword("API key in config") == "CRITICAL"
        assert _severity_from_keyword("jwt token exposed") == "CRITICAL"

    def test_severity_keywords_warning(self):
        assert _severity_from_keyword("orphaned flow detected") == "WARNING"
        assert _severity_from_keyword("missing error handler") == "WARNING"
        assert _severity_from_keyword("unused configuration") == "WARNING"

    def test_severity_keywords_info(self):
        assert _severity_from_keyword("flow naming convention check") == "INFO"

    def test_normalise_security_warning(self):
        raw = {
            "security_warnings": [
                {"location": "config.yaml:5", "issue": "Hardcoded password detected"}
            ]
        }
        issues = _normalise_findings(raw)
        assert len(issues) == 1
        assert issues[0]["severity"] == "CRITICAL"
        assert issues[0]["type"] == "security"
        assert "MULE-SEC" in issues[0]["id"]

    def test_normalise_orphaned_flows(self):
        raw = {
            "orphan_results": {
                "orphaned_flows": ["unusedFlow", "anotherDeadFlow"]
            }
        }
        issues = _normalise_findings(raw)
        assert len(issues) == 2
        assert all(i["rule_id"] == "MULE-ORPHAN-FLOW" for i in issues)
        assert all(i["severity"] == "WARNING" for i in issues)

    def test_normalise_dependency_issues(self):
        raw = {
            "dependency_results": {
                "unused_dependencies": ["com.example:unused-lib:1.0.0"]
            }
        }
        issues = _normalise_findings(raw)
        assert len(issues) == 1
        assert issues[0]["severity"] == "INFO"
        assert issues[0]["type"] == "dependencies"

    def test_normalise_empty_raw_returns_empty_list(self):
        assert _normalise_findings({}) == []



    def test_heuristic_xml_finds_common_risks(self):
        xml = """<mule>
  <flow name="unusedHelperFlow">
    <db:my-sql-connection user="admin" password="secret"/>
    <db:sql>SELECT * FROM users WHERE id = #[attributes.queryParams.id]</db:sql>
    <logger level="DEBUG" message="debug"/>
  </flow>
</mule>"""
        issues = _heuristic_xml_findings(xml)
        rule_ids = {i["rule_id"] for i in issues}
        assert "MULE-HARDCODED-PASSWORD" in rule_ids
        assert "MULE-DEBUG-LOGGER" in rule_ids
        assert "MULE-SQL-INJECTION-RISK" in rule_ids
        assert "MULE-ORPHAN-FLOW" in rule_ids

    def test_normalise_multiple_categories(self):
        raw = {
            "security_warnings": [{"location": "x", "issue": "password found"}],
            "orphan_results": {"orphaned_flows": ["oldFlow"]},
        }
        issues = _normalise_findings(raw)
        assert len(issues) == 2
        severities = {i["severity"] for i in issues}
        assert "CRITICAL" in severities
        assert "WARNING" in severities


# ─── FastAPI Endpoint Tests ───────────────────────────────────────────────────

class TestAPIEndpoints:

    def test_health_endpoint_does_not_require_bedrock(self):
        """Health check must pass without any Bedrock connection."""
        from fastapi.testclient import TestClient
        from main import app

        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "1.0.0"

    def test_review_endpoint_rejects_invalid_language(self):
        """Unknown languages must return 422 Unprocessable Entity."""
        from fastapi.testclient import TestClient
        from main import app

        with TestClient(app) as client:
            response = client.post(
                "/api/review",
                json={"code": "print('hello')", "language": "cobol"},
            )
        assert response.status_code == 422

    def test_review_endpoint_rejects_empty_code(self):
        """Whitespace-only code must return 422."""
        from fastapi.testclient import TestClient
        from main import app

        with TestClient(app) as client:
            response = client.post(
                "/api/review",
                json={"code": "   ", "language": "python"},
            )
        assert response.status_code == 422

    def test_review_endpoint_rejects_oversized_code(self):
        """Code exceeding MAX_CODE_LENGTH must return 413."""
        from fastapi.testclient import TestClient
        from main import app

        with TestClient(app) as client:
            response = client.post(
                "/api/review",
                json={"code": "x = 1\n" * 10000, "language": "python"},
            )
        assert response.status_code == 413

    def test_mulesoft_project_endpoint_passes_precomputed_static_result(self, monkeypatch):
        """Project zip review should reuse precomputed static_result in pipeline call."""
        from fastapi.testclient import TestClient
        import main as main_module

        expected_static = {
            "issues": [{"id": "MULE-SEC-001", "severity": "CRITICAL"}],
            "issue_count": 1,
            "overall_risk": "HIGH",
            "raw_validator_output": {"security_warnings": [{"issue": "Hardcoded password"}]},
        }

        call_args = {}

        def fake_static_analysis(project_path):
            return expected_static

        async def fake_pipeline(code, language, filename="", static_result=None):
            call_args["language"] = language
            call_args["filename"] = filename
            call_args["static_result"] = static_result
            return {
                "status": "success",
                "language": language,
                "analysis": {
                    "language": language,
                    "issues": expected_static["issues"],
                    "issue_count": 1,
                    "overall_risk": "HIGH",
                },
                "coaching": {"coaching": []},
                "refactor": {"refactored_code": "", "changes_made": [], "confidence": 0.0},
                "validation": {
                    "correctness_score": 100,
                    "logic_preserved": True,
                    "issues_addressed": 100,
                    "flags": [],
                    "recommend_regenerate": False,
                },
                "processing_time_seconds": 0.01,
            }

        monkeypatch.setattr(main_module, "run_static_analysis_on_project", fake_static_analysis)
        monkeypatch.setattr(main_module, "run_review_pipeline", fake_pipeline)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("src/main/mule/main.xml", "<mule></mule>")
        zip_buffer.seek(0)

        with TestClient(main_module.app) as client:
            response = client.post(
                "/api/review/mulesoft-project",
                files={"file": ("project.zip", zip_buffer.getvalue(), "application/zip")},
            )

        assert response.status_code == 200
        assert call_args["language"] == "mulesoft"
        assert call_args["filename"] == "project.zip"
        assert call_args["static_result"] == expected_static
        data = response.json()
        assert data["analysis"]["mulesoft_static"] == expected_static["raw_validator_output"]
