"""
PolyDev Coach - Configuration
Loads all environment variables with validation.
"""
import os
from dataclasses import dataclass


@dataclass
class Settings:
    # Gradient AI
    gradient_api_key: str
    gradient_base_url: str

    # Agent IDs (set after creating agents in Gradient UI)
    orchestrator_agent_id: str
    analyzer_agent_id: str
    coach_agent_id: str
    refactor_agent_id: str
    validator_agent_id: str
    optimizer_agent_id: str

    # App
    environment: str
    allowed_origins: list
    max_code_length: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        missing = []
        required = [
            "GRADIENT_API_KEY",
            "ANALYZER_AGENT_ID",
            "COACH_AGENT_ID",
            "REFACTOR_AGENT_ID",
            "VALIDATOR_AGENT_ID",
            "OPTIMIZER_AGENT_ID",
        ]
        for key in required:
            if not os.getenv(key):
                missing.append(key)
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Please copy .env.example to .env and fill in the values."
            )

        origins_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
        return cls(
            gradient_api_key=os.getenv("GRADIENT_API_KEY"),
            gradient_base_url=os.getenv(
                "GRADIENT_BASE_URL",
                "https://api.digitalocean.com/v1/gen-ai"
            ),
            orchestrator_agent_id=os.getenv("ORCHESTRATOR_AGENT_ID", ""),
            analyzer_agent_id=os.getenv("ANALYZER_AGENT_ID"),
            coach_agent_id=os.getenv("COACH_AGENT_ID"),
            refactor_agent_id=os.getenv("REFACTOR_AGENT_ID"),
            validator_agent_id=os.getenv("VALIDATOR_AGENT_ID"),
            optimizer_agent_id=os.getenv("OPTIMIZER_AGENT_ID"),
            environment=os.getenv("ENVIRONMENT", "development"),
            allowed_origins=[o.strip() for o in origins_raw.split(",")],
            max_code_length=int(os.getenv("MAX_CODE_LENGTH", "15000")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


# Singleton — loaded once at startup
settings = Settings.from_env()
