from __future__ import annotations
import os
from dotenv import load_dotenv
load_dotenv(override=True)

class Settings:
    """
    A centralized class to hold all application settings loaded from environment variables.
    """

    def __init__(self):
        # Optional: no database is wired up yet, so this must not block startup.
        self.DATABASE_URL: str | None = self._get_optional("DATABASE_URL")

        # Where cloned/extracted projects are stored temporarily for the pipeline.
        # Kept inside the project folder so everything stays self-contained.
        self.TEMP_STORAGE_PATH: str = self._get_optional(
            "TEMP_STORAGE_PATH", default="./temp/repos"
        )

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
