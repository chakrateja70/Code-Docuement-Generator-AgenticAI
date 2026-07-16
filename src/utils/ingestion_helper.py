from __future__ import annotations

import io
import os
import re
import shutil
import stat
import uuid
import zipfile
from urllib.parse import urlparse, urlunparse, quote

from git import Repo, GitCommandError

from src.config.settings import settings
from src.core.exceptions import (
    InvalidGitUrlException,
    PrivateRepoAuthException,
    RepoCloneException,
    InvalidZipFileException,
    ZipExtractionException,
)
from src.utils.scanner import NOISE_DIRS, NOISE_FILES

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


def clone_repo(url: str, access_token: str | None = None) -> str:
    """
    Clone a repo into a unique temp subfolder and return its local path.

    - Public repos: pass just the URL.
    - Private repos: pass an access_token; it's injected into the clone URL.

    Uses a shallow clone (depth=1) — the pipeline only needs the current
    file tree, not full history. Cleans up the temp folder on any failure.
    """
    base_dir = settings.TEMP_STORAGE_PATH
    dest_dir = os.path.join(base_dir, uuid.uuid4().hex)

    clone_url = _build_authed_url(url, access_token) if access_token else url

    # Never prompt interactively; fail fast instead of hanging on a prompt.
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
        raise RepoCloneException()
    except Exception:
        _cleanup(dest_dir)
        raise RepoCloneException()

    # Physically remove noise (.git, committed dist/vendor, __pycache__, ...)
    # so downstream steps walk a clean folder.
    _prune_noise(dest_dir)

    return dest_dir


def extract_zip(file_bytes: bytes, filename: str) -> str:
    """
    Extract an uploaded zip archive into a unique temp subfolder.

    Mirrors clone_repo: lands the project under TEMP_STORAGE_PATH so the rest
    of the pipeline is source-agnostic. Returns the extracted root path.

    Safety:
      - Validates the payload is a real zip.
      - Guards against Zip Slip (entries with '..' or absolute paths that
        would escape the destination directory).
      - Cleans up the temp folder on any failure.
    """
    if not filename or not filename.lower().endswith(".zip"):
        raise InvalidZipFileException("Uploaded file must be a .zip archive.")

    if not file_bytes:
        raise InvalidZipFileException("Uploaded zip file is empty.")

    buffer = io.BytesIO(file_bytes)
    if not zipfile.is_zipfile(buffer):
        raise InvalidZipFileException("Uploaded file is not a valid zip archive.")

    base_dir = settings.TEMP_STORAGE_PATH
    dest_dir = os.path.join(base_dir, uuid.uuid4().hex)
    dest_root = os.path.realpath(dest_dir)

    try:
        os.makedirs(dest_dir, exist_ok=True)
        with zipfile.ZipFile(buffer) as zf:
            if zf.testzip() is not None:
                raise InvalidZipFileException("Zip archive is corrupt.")

            safe_members = []
            for member in zf.namelist():
                target = os.path.realpath(os.path.join(dest_dir, member))
                if not (target == dest_root or target.startswith(dest_root + os.sep)):
                    raise InvalidZipFileException(
                        "Zip archive contains unsafe file paths."
                    )
                # Skip noise (node_modules, .venv, __pycache__, .DS_Store, ...)
                # so junk never lands on disk in the first place.
                if _is_noise_member(member):
                    continue
                safe_members.append(member)

            zf.extractall(dest_dir, members=safe_members)
    except InvalidZipFileException:
        _cleanup(dest_dir)
        raise
    except zipfile.BadZipFile:
        _cleanup(dest_dir)
        raise InvalidZipFileException("Uploaded file is not a valid zip archive.")
    except Exception:
        _cleanup(dest_dir)
        raise ZipExtractionException()

    return dest_dir


def _on_rm_error(func, path, _exc):
    """
    rmtree onexc handler: clear the read-only bit and retry.

    Git pack files under .git are read-only on Windows, which makes a plain
    rmtree fail. Chmod to writable, then re-run the failed operation.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _is_noise_member(member: str) -> bool:
    """
    True if a zip member path is noise — i.e. any path segment is a noise
    dir, or the filename itself is a noise file.
    """
    # Normalize separators; zip always uses "/".
    parts = member.replace("\\", "/").split("/")
    for seg in parts[:-1]:
        if seg in NOISE_DIRS:
            return True
    return parts[-1] in NOISE_FILES


def _prune_noise(root: str) -> None:
    """
    Physically remove noise dirs/files from an already-populated folder.

    Used after git clone (a shallow clone can still contain committed junk
    like a vendored dist/ or, on Windows, the .git dir itself).
    """
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # Remove noise directories and stop descending into them.
        for d in list(dirnames):
            if d in NOISE_DIRS:
                shutil.rmtree(os.path.join(dirpath, d), onexc=_on_rm_error)
                dirnames.remove(d)
        for f in filenames:
            if f in NOISE_FILES:
                try:
                    fpath = os.path.join(dirpath, f)
                    os.chmod(fpath, stat.S_IWRITE)
                    os.remove(fpath)
                except OSError:
                    pass


def _cleanup(path: str) -> None:
    """Best-effort removal of a temp folder; never raises."""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, onexc=_on_rm_error)
    except Exception:
        pass
