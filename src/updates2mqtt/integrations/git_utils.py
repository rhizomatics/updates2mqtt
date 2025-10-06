import datetime
import subprocess
from pathlib import Path

import structlog

log = structlog.get_logger()


def git_trust(repo_path: Path, git_path: Path) -> bool:
    try:
        subprocess.run(f"{git_path} config --global --add safe.directory {repo_path}", check=True, shell=True, cwd=repo_path)
        return True
    except Exception as e:
        log.warn("GIT Unable to trust repo at %s: %s", repo_path, e)
        return False


def git_timestamp(repo_path: Path, git_path: Path) -> datetime.datetime | None:
    result = None
    try:
        result = subprocess.run(
            str(git_path) + r" log -1 --format=%cI --no-show-signature",
            cwd=repo_path,
            shell=True,
            text=True,
            capture_output=True,
            check=True,
        )
        return datetime.datetime.fromisoformat(result.stdout.strip())
    except Exception as e:
        log.warn("GIT Unable to parse timestamp at %s - %s: %s", repo_path, result.stdout if result else "<NO RESULT>", e)
    return None


def git_check_update_available(repo_path: Path, git_path: Path, timeout: int = 120) -> bool:
    result = None
    try:
        # check if remote repo ahead
        result = subprocess.run(
            f"{git_path} fetch;{git_path} status -uno",
            capture_output=True,
            text=True,
            shell=True,
            check=True,
            cwd=repo_path,
            timeout=timeout,
        )
        if result.returncode == 0 and "Your branch is behind" in result.stdout:
            log.info("Local git repo update available", path=repo_path, status=result.stdout.strip())
            return True
    except Exception as e:
        log.warn("GIT Unable to check status %s: %s", result.stdout if result else "<NO RESULT>", e)
    return False


def git_pull(repo_path: Path, git_path: Path) -> bool:
    log.info("GIT Pulling git at %s", repo_path)
    proc = subprocess.run(f"{git_path} pull", shell=True, check=False, cwd=repo_path, timeout=300)
    if proc.returncode == 0:
        log.info("GIT pull at %s successful", repo_path)
        return True
    log.warn("GIT pull at %s failed: %s", repo_path, proc.returncode)
    return False
