# Python Enterprise Patterns & Best Practices

This knowledge base is used by the PolyDev Coach AI agents (running on Amazon Nova via
AWS Bedrock) for Python coaching. It is uploaded to Amazon S3 and indexed by Amazon Bedrock
Knowledge Bases for RAG retrieval by the Nova Lite Coach agent.

---

## 1. Security

### Never Hardcode Secrets
**Bad:**
```python
DB_PASSWORD = "production_secret_123"
API_KEY = "sk-abc123"
```

**Good:**
```python
import os
DB_PASSWORD = os.environ["DB_PASSWORD"]  # Raises if missing — intentional
API_KEY = os.environ.get("API_KEY")      # Returns None if missing
```

**Reference:** OWASP — A02:2021 Cryptographic Failures; 12-Factor App §Config

### Input Validation
Always validate and sanitise input. Use Pydantic for API payloads:
```python
from pydantic import BaseModel, EmailStr, validator

class UserRequest(BaseModel):
    email: EmailStr
    name: str

    @validator("name")
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Name cannot be empty")
        return v.strip()
```

---

## 2. Error Handling

### Never Use Bare Except
**Bad:**
```python
try:
    result = process()
except:  # Catches SystemExit, KeyboardInterrupt, etc.
    pass
```

**Good:**
```python
import logging
logger = logging.getLogger(__name__)

try:
    result = process()
except ValueError as exc:
    logger.warning("Invalid input: %s", exc)
    raise
except Exception as exc:
    logger.error("Unexpected error in process(): %s", exc, exc_info=True)
    raise RuntimeError("Processing failed") from exc
```

### Exception Hierarchy
Design a custom exception hierarchy:
```python
class AppError(Exception):
    """Base exception for all application errors."""

class ValidationError(AppError):
    """Input validation failed."""

class ExternalServiceError(AppError):
    """Third-party service call failed."""
    def __init__(self, service: str, message: str):
        self.service = service
        super().__init__(f"[{service}] {message}")
```

**Reference:** Python Docs — Exception Hierarchy; Effective Python Item 87

---

## 3. Code Structure

### Single Responsibility Principle
Each function should do one thing. If it needs an "and" to describe it, split it.

**Bad:**
```python
def fetch_and_process_and_save_users():
    # 80 lines doing everything
```

**Good:**
```python
def fetch_users(api_client: APIClient) -> list[User]:
    ...

def process_users(users: list[User]) -> list[ProcessedUser]:
    ...

def save_users(users: list[ProcessedUser], db: Database) -> None:
    ...
```

### Function Length
- Keep functions under 20–30 lines as a guideline
- If a function exceeds 50 lines, it almost certainly should be split

### Type Hints (Python 3.9+)
```python
from typing import Optional

def get_user(user_id: int, include_deleted: bool = False) -> Optional[dict]:
    ...
```

---

## 4. Logging

### Use Structured Logging
**Bad:**
```python
print(f"Processing user {user_id}")
```

**Good:**
```python
import logging
logger = logging.getLogger(__name__)

logger.info("Processing user | user_id=%s | source=%s", user_id, source)
logger.error("Failed to fetch user | user_id=%s", user_id, exc_info=True)
```

### Configure Logging at Application Root
```python
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        }
    },
    "formatters": {
        "json": {"class": "pythonjsonlogger.jsonlogger.JsonFormatter"}
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}
logging.config.dictConfig(LOGGING_CONFIG)
```

---

## 5. Performance

### String Concatenation in Loops
**Bad:**
```python
result = ""
for item in items:
    result += str(item)  # O(n²) — creates new string each iteration
```

**Good:**
```python
result = "".join(str(item) for item in items)  # O(n)
```

### Use Context Managers for Resources
```python
# Good: file always closed even if exception occurs
with open("data.txt", "r") as f:
    content = f.read()

# Good: database connection always returned to pool
with db.get_connection() as conn:
    conn.execute(query)
```

---

## 6. Dependency Injection

Inject dependencies rather than creating them inside functions:

**Bad:**
```python
def get_user(user_id: int) -> dict:
    db = Database(os.environ["DB_URL"])  # Hard to test
    return db.query(user_id)
```

**Good:**
```python
def get_user(user_id: int, db: Database) -> dict:
    return db.query(user_id)  # Easy to mock in tests
```

---

## 7. 12-Factor App Principles (for APIs)

| Factor | Practice |
|--------|----------|
| Config | All config in environment variables |
| Logs | Treat logs as event streams (stdout) |
| Processes | Stateless — no local session state |
| Port binding | Self-contained — expose via port |
| Concurrency | Scale by running more processes |

**Reference:** 12factor.net

---

## 8. PEP8 Key Rules

| Rule | Description |
|------|-------------|
| E501 | Max line length 79–120 chars |
| E711 | Compare to None with `is`, not `==` |
| W291 | No trailing whitespace |
| F401 | Remove unused imports |
| E741 | Avoid ambiguous variable names (l, O, I) |

---

## 9. Testing Patterns

```python
import pytest
from unittest.mock import MagicMock

def test_get_user_returns_user_when_exists():
    # Arrange
    mock_db = MagicMock()
    mock_db.query.return_value = {"id": 1, "name": "Alice"}

    # Act
    result = get_user(user_id=1, db=mock_db)

    # Assert
    assert result["name"] == "Alice"
    mock_db.query.assert_called_once_with(1)
```

**Reference:** pytest documentation; unittest.mock

---

## 16. Secret Hygiene Note

All code examples in this knowledge base must use placeholders only.
Never include real API keys, access tokens, passwords, certificates, or customer data in example snippets.

