import os
import uuid
import shutil

from git import Repo, GitCommandError

from src.config.settings import settings
from src.core.exceptions import RepoCloneException


def clone_repo(url: str) -> str:
    """
    Clone a Git repo into a unique temp subfolder and return its local path.

    Shallow clone (depth=1) — we only need the current file tree, not history.
    Cleans up the temp folder if the clone fails.
    """
    base_dir = settings.TEMP_STORAGE_PATH
    dest_dir = os.path.join(base_dir, uuid.uuid4().hex)

    print(f"[clone_repo] URL: {url}")
    print(f"[clone_repo] Base dir: {base_dir}")
    print(f"[clone_repo] Destination: {dest_dir}")

    try:
        os.makedirs(base_dir, exist_ok=True)
        print(f"[clone_repo] Base dir ready.")
        print("[clone_repo] Cloning (depth=1)...")
        Repo.clone_from(url.strip(), dest_dir, depth=1)
        print("[clone_repo] Clone succeeded.")
    except GitCommandError as exc:
        print(f"[clone_repo] Clone FAILED: {exc}")
        _cleanup(dest_dir)
        raise RepoCloneException()

    print(f"[clone_repo] Contents: {os.listdir(dest_dir)}")
    return dest_dir


def _cleanup(path: str) -> None:
    """Best-effort removal of a temp folder; never raises."""
    if os.path.isdir(path):
        print(f"[_cleanup] Removing {path}")
        shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    print("=== Git Clone Test ===")
    url = input("Enter Git repo URL: ").strip()

    if not url:
        print("No URL provided. Exiting.")
    else:
        try:
            path = clone_repo(url)
            print("\n=== RESULT ===")
            print(f"Cloned to: {path}")
            print(f"Exists: {os.path.isdir(path)}")
        except RepoCloneException as exc:
            print("\n=== FAILED ===")
            print(f"Error: {exc.detail}")
