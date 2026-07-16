"""
Ingestion helpers for the Git-repo path of the pipeline.

Responsibilities (mechanical, no LLM calls):
- Sanitize and validate a user-supplied Git URL.
- Check whether a remote repo is reachable (public) without cloning.
- Clone a repo (public or private-with-token) into a unique temp folder.

All network/git operations are wrapped in try/except and raise the
ingestion-specific exceptions defined in src.core.exceptions.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from urllib.parse import urlparse, urlunparse, quote

from git import Repo, GitCommandError

from src.config.settings import settings
from src.core.exceptions import (
    InvalidGitUrlException,
    RepoNotFoundException,
    PrivateRepoAuthException,
    RepoCloneException,
)

# Hosts we currently support cloning from over HTTPS.
_ALLOWED_HOSTS = {
    "github.com",
    "www.github.com",
    "gitlab.com",
    "www.gitlab.com",
    "bitbucket.org",
    "www.bitbucket.org",
}

# Basic shape of an HTTPS git URL ending in an optional .git suffix.
_URL_PATTERN = re.compile(r"^https://[\w.-]+/[\w./-]+?(?:\.git)?/?$")


def sanitize_git_url(url: str) -> str:
    """
    Trim, validate, and normalize a Git repository URL.

    - Strips surrounding whitespace.
    - Enforces https scheme and an allowed host.
    - Rejects any embedded credentials (e.g. https://user:pass@host/...),
      since credentials must come through the dedicated token field.

    Returns the cleaned URL. Raises InvalidGitUrlException on any problem.
    """
    if not url or not url.strip():
        raise InvalidGitUrlException("Repository URL must not be empty.")

    cleaned = url.strip()

    try:
        parsed = urlparse(cleaned)
    except ValueError:
        raise InvalidGitUrlException()

    if parsed.scheme != "https":
        raise InvalidGitUrlException("Only https:// Git URLs are supported.")

    # Reject credentials baked into the URL — token must be passed separately.
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise InvalidGitUrlException("Credentials must not be embedded in the URL.")

    host = parsed.netloc.lower()
    if host not in _ALLOWED_HOSTS:
        raise InvalidGitUrlException(
            f"Unsupported Git host '{parsed.netloc}'. "
            "Supported: GitHub, GitLab, Bitbucket."
        )

    if not _URL_PATTERN.match(cleaned):
        raise InvalidGitUrlException("Repository URL is malformed.")

    # Normalize: drop any trailing slash, keep as-is otherwise.
    normalized = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")
    )
    return normalized


def _build_authed_url(url: str, access_token: str) -> str:
    """
    Inject an access token into an https git URL for private cloning.

    Produces https://<token>@host/path — the token is URL-encoded so
    special characters don't break the URL.
    """
    parsed = urlparse(url)
    safe_token = quote(access_token, safe="")
    netloc = f"{safe_token}@{parsed.netloc}"
    return urlunparse(
        (parsed.scheme, netloc, parsed.path, "", "", "")
    )


def check_repo_accessibility(url: str, access_token: str | None = None) -> str:
    """
    Probe a remote repo WITHOUT cloning, using `git ls-remote`.

    Credential prompts are disabled so a private/nonexistent repo fails fast
    instead of hanging on an interactive prompt.

    Returns "public" or "private" depending on whether a token was needed.
    Raises:
      - RepoNotFoundException if the repo can't be reached at all.
      - PrivateRepoAuthException if a token was supplied but rejected.
    """
    probe_url = _build_authed_url(url, access_token) if access_token else url

    # Never prompt interactively; fail immediately on missing credentials.
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "echo",
    }

    try:
        Repo().git.ls_remote(probe_url, env=env)
    except GitCommandError as exc:
        stderr = (exc.stderr or "").lower()
        if access_token:
            # Token was provided but the remote still refused / not found.
            if "authentication" in stderr or "403" in stderr or "denied" in stderr:
                raise PrivateRepoAuthException()
            raise RepoNotFoundException()
        # No token: could be genuinely missing OR private. Treat as not-found
        # so the caller (public flow) surfaces a clear message.
        raise RepoNotFoundException(
            "Repository not found. If it is private, choose the private option "
            "and provide an access token."
        )
    except Exception:
        raise RepoNotFoundException()

    return "private" if access_token else "public"


def clone_repo(url: str, access_token: str | None = None) -> str:
    """
    Clone a repo into a unique temp subfolder and return its local path.

    Uses a shallow clone (depth=1) — the pipeline only needs the current
    file tree, not full history. Cleans up the temp folder on any failure.
    """
    base_dir = settings.TEMP_STORAGE_PATH
    dest_dir = os.path.join(base_dir, uuid.uuid4().hex)

    clone_url = _build_authed_url(url, access_token) if access_token else url

    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "echo",
    }

    try:
        os.makedirs(base_dir, exist_ok=True)
        Repo.clone_from(clone_url, dest_dir, depth=1, env=env)
    except GitCommandError as exc:
        _cleanup(dest_dir)
        stderr = (exc.stderr or "").lower()
        if "authentication" in stderr or "403" in stderr or "denied" in stderr:
            raise PrivateRepoAuthException()
        if "not found" in stderr or "repository" in stderr:
            raise RepoNotFoundException()
        raise RepoCloneException()
    except Exception:
        _cleanup(dest_dir)
        raise RepoCloneException()

    return dest_dir


def _cleanup(path: str) -> None:
    """Best-effort removal of a temp folder; never raises."""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
