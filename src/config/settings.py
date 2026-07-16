from __future__ import annotations
import os
from dotenv import load_dotenv
load_dotenv(override=True)

class Settings:
    """
    A centralized class to hold all application settings loaded from environment variables.
    """
    def __init__(self):
        # Base folder holding one working directory per job: temp/jobs/{job_id}/
        self.JOBS_BASE_PATH: str = "./temp/jobs"
        self.MAX_UPLOAD_SIZE_MB: int = 400

        self.ANTHROPIC_API_KEY: str = self._get_required("ANTHROPIC_API_KEY")
        self.MODEL_SMALL: str = "claude-haiku-4-5"
        self.MODEL_MEDIUM: str = "claude-sonnet-5"
        self.MODEL_LARGE: str = "claude-opus-4-8"

        self.MAX_RETRIES: int = 3
        self.LLM_TEMPERATURE: float = -1

    @staticmethod
    def _get_required(key: str) -> str:
        """Get a required environment variable or raise ValueError."""
        value = os.getenv(key)
        if not value:
            raise ValueError(f"{key} not found in environment variables. Please check your .env file.")
        return value

    @staticmethod
    def _get_optional(key: str, default: str | None = None) -> str | None:
        """Get an optional environment variable, falling back to a default."""
        value = os.getenv(key)
        return value if value else default


# Create a single instance of the settings to be imported across the application
settings = Settings()
