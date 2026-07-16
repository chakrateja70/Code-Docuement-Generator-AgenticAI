import os
from typing import Literal, Optional

from fastapi import APIRouter, File, UploadFile, status
from pydantic import BaseModel, HttpUrl, field_validator, model_validator

from src.config.settings import settings
from src.core.exceptions import InvalidZipFileException
from src.utils.ingestion_helper import (
    sanitize_git_url,
    clone_repo,
    extract_zip,
)
from src.utils.scanner import build_project_snapshot

router = APIRouter(prefix="/ingest", tags=["ingestion"])

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
            raise ValueError("Access Token is required for private repositories.")
        return self


class GitRepoResponse(BaseModel):
    """Response returned after a repo is successfully cloned."""
    message: str
    visibility: str
    repo_name: str
    clone_path: str
    project_snapshot: dict


class FileUploadResponse(BaseModel):
    """Response returned after an uploaded zip is successfully extracted."""
    message: str
    project_name: str
    extract_path: str
    project_snapshot: dict


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
      2. Clone into a unique temp folder (token used only for private repos).
    """
    # Only pass a token when the repo is private.
    token = payload.access_token if payload.visibility == "private" else None

    # 1. Sanitize / normalize the URL (HttpUrl -> str).
    clean_url = sanitize_git_url(str(payload.repo_url))

    # 2. Clone into temp. A bad token / missing private repo surfaces here.
    clone_path = clone_repo(clean_url, token)

    # 3. Scan the cloned folder into a structured project_snapshot.
    project_snapshot = build_project_snapshot(clone_path)

    repo_name = clean_url.rstrip("/").split("/")[-1].removesuffix(".git")

    return GitRepoResponse(
        message="Repository cloned successfully.",
        visibility=payload.visibility,
        repo_name=repo_name,
        clone_path=clone_path,
        project_snapshot=project_snapshot,
    )


@router.post(
    "/file-upload",
    status_code=status.HTTP_201_CREATED,
    response_model=FileUploadResponse,
)
async def upload_file(file: UploadFile = File(...)) -> FileUploadResponse:
    """
    Ingest a project from an uploaded zip file.

    Flow:
      1. Validate it's a .zip within the size limit.
      2. Extract into a unique temp folder (same location as git clones)
         so downstream steps are source-agnostic.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise InvalidZipFileException("Uploaded file must be a .zip archive.")

    # Read the upload and enforce the size limit before extracting.
    contents = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise InvalidZipFileException(
            f"Zip file exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB limit."
        )

    extract_path = extract_zip(contents, file.filename)

    # Scan the extracted folder into a structured project_snapshot.
    project_snapshot = build_project_snapshot(extract_path)

    # Project name = the zip's base filename without extension.
    project_name = os.path.splitext(os.path.basename(file.filename))[0]

    return FileUploadResponse(
        message="Zip file uploaded and extracted successfully.",
        project_name=project_name,
        extract_path=extract_path,
        project_snapshot=project_snapshot,
    )
