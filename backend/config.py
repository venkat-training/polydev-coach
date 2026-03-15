"""
PolyDev Coach — AWS Configuration
Replaces config.py for the Amazon Nova hackathon.
"""
import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file


@dataclass
class Settings:
    # AWS
    aws_region: str
    aws_access_key_id: str       # Leave empty to use IAM role / instance profile
    aws_secret_access_key: str   # Leave empty to use IAM role / instance profile

    # Bedrock Knowledge Base (created in AWS Console → Bedrock → Knowledge Bases)
    knowledge_base_id: str

    # App
    environment: str
    allowed_origins: List[str]
    max_code_length: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        origins_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
        return cls(
            aws_region=os.getenv("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
            knowledge_base_id=os.getenv("BEDROCK_KNOWLEDGE_BASE_ID", ""),
            environment=os.getenv("ENVIRONMENT", "development"),
            allowed_origins=[o.strip() for o in origins_raw.split(",")],
            max_code_length=int(os.getenv("MAX_CODE_LENGTH", "15000")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


settings = Settings.from_env()
