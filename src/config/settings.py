from __future__ import annotations
import os
from dotenv import load_dotenv
load_dotenv(override=True)

class Settings:
    """
    A centralized class to hold all application settings loaded from environment variables.
    """

    def __init__(self):
        self.TEMP_STORAGE_PATH: str =  "./temp/repos"
        self.MAX_UPLOAD_SIZE_MB: int = int("200")

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
