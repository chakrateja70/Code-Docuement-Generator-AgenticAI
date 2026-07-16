from typing import Literal, Optional

from fastapi import APIRouter, status
from pydantic import BaseModel, HttpUrl, field_validator, model_validator

from src.utils.ingestion_helper import (
    sanitize_git_url,
    check_repo_accessibility,
    clone_repo,
)

router = APIRouter(prefix="/ingest", tags=["ingestion"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class GitRepoRequest(BaseModel):
    """Payload for ingesting a project from a Git repository URL."""

    repo_url: HttpUrl
    visibility: Literal["public", "private"]
    access_token: Optional[str] = None

    @field_validator("access_token")
    @classmethod
    def _strip_token(cls, v: Optional[str]) -> Optional[str]:
        # Normalize empty/whitespace tokens to None so the check below works.
        if v is None:
            return None
        v = v.strip()
        return v or None

    @model_validator(mode="after")
    def _require_token_for_private(self) -> "GitRepoRequest":
        if self.visibility == "private" and not self.access_token:
            raise ValueError("access_token is required for private repositories.")
        return self


class GitRepoResponse(BaseModel):
    """Response returned after a repo is successfully cloned."""
    message: str
    visibility: str
    repo_name: str
    clone_path: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/git-repo",
    status_code=status.HTTP_201_CREATED,
    response_model=GitRepoResponse,
)
async def ingest_git_repo(payload: GitRepoRequest) -> GitRepoResponse:
    """
    Ingest a project from a Git repository URL.

    Flow:
      1. Sanitize & validate the URL.
      2. Confirm the repo is reachable (public) or auth is valid (private).
      3. Clone into a unique temp folder for the next pipeline steps.
    """
    # Only pass a token when the repo is private.
    token = payload.access_token if payload.visibility == "private" else None

    # 1. Sanitize / normalize the URL (HttpUrl -> str).
    clean_url = sanitize_git_url(str(payload.repo_url))

    # 2. Verify accessibility without cloning.
    visibility = check_repo_accessibility(clean_url, token)

    # 3. Clone into temp.
    clone_path = clone_repo(clean_url, token)

    repo_name = clean_url.rstrip("/").split("/")[-1].removesuffix(".git")

    return GitRepoResponse(
        message="Repository cloned successfully.",
        visibility=visibility,
        repo_name=repo_name,
        clone_path=clone_path,
    )


@router.post("/file-upload", status_code=status.HTTP_201_CREATED)
async def upload_file():
    """
    Endpoint to handle file uploads for ingestion.
    """
    # Placeholder for file upload logic
    return {"message": "File uploaded and ingested successfully."}
