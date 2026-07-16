"""
Manual test: clone a Git repo into a job folder.

Run from the project root:  python -m tests.git_clone
"""

from src.core.exceptions import RepoCloneException
from src.utils.ingestion_helper import clone_repo, new_job_id, cleanup_job


if __name__ == "__main__":
    url = input("Enter Git repo URL: ").strip()

    if not url:
        raise SystemExit("No URL provided.")

    job_id = new_job_id()
    try:
        path = clone_repo(url, job_id)
        print(f"job_id: {job_id}")
        print(f"cloned to: {path}")
    except RepoCloneException as exc:
        cleanup_job(job_id)
        print(f"failed: {exc.detail}")
