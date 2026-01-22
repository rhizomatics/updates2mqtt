import datetime
import re
import subprocess
from pathlib import Path
from re import Match

import structlog

log = structlog.get_logger()


def git_trust(repo_path: Path, git_path: Path) -> bool:
    try:
        subprocess.run(f"{git_path} config --global --add safe.directory {repo_path}", check=True, shell=True, cwd=repo_path)
        return True
    except Exception as e:
        log.warn("GIT Unable to trust repo at %s: %s", repo_path, e, action="git_trust")
        return False


def git_iso_timestamp(repo_path: Path, git_path: Path) -> str | None:
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
        # round-trip the iso format for pythony consistency
        return datetime.datetime.fromisoformat(result.stdout.strip()).isoformat()
    except subprocess.CalledProcessError as cpe:
        log.warn("GIT No result from git log at %s: %s", repo_path, cpe, action="git_iso_timestamp")
    except Exception as e:
        log.error(
            "GIT Unable to parse timestamp at %s - %s: %s",
            repo_path,
            result.stdout if result else "<NO RESULT>",
            e,
            action="git_iso_timestamp",
        )
    return None


def git_local_digest(repo_path: Path, git_path: Path) -> str | None:
    result = None
    try:
        result = subprocess.run(
            f"{git_path} rev-parse HEAD",
            cwd=repo_path,
            shell=True,
            text=True,
            capture_output=True,
            check=True,
        )
        if result.returncode == 0:
            log.debug("Local git rev-parse", action="git_local_digest", path=repo_path, version=result.stdout.strip())
            return result.stdout.strip()[:15]
    except subprocess.CalledProcessError as cpe:
        log.warn("GIT No result from git rev-parse at %s: %s", repo_path, cpe, action="git_local_digest")
    except Exception as e:
        log.error(
            "GIT Unable to retrieve version at %s - %s: %s",
            repo_path,
            result.stdout if result else "<NO RESULT>",
            e,
            action="git_local_digest",
        )
    return None


def git_check_update_available(repo_path: Path, git_path: Path, timeout: int = 120) -> int:
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
        if result.returncode == 0:
            count_match: Match[str] | None = re.search(
                r"Your branch is behind.*by (\d+) commit", result.stdout, flags=re.MULTILINE
            )
            if count_match and count_match.groups():
                log.debug(
                    "Local git repo update available: %s (%s)",
                    count_match.group(1),
                    result.stdout.strip(),
                    action="git_check",
                    path=repo_path,
                )
                return int(count_match.group(1))
            log.debug("Local git repo no update available", action="git_check", path=repo_path, status=result.stdout.strip())
            return 0

        log.debug(
            "No git update available",
            action="git_check",
            path=repo_path,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except Exception as e:
        log.warn("GIT Unable to check status %s: %s", result.stdout if result else "<NO RESULT>", e, action="git_check")
    return 0


def git_pull(repo_path: Path, git_path: Path) -> bool:
    log.info("GIT Pulling git at %s", repo_path, action="git_pull")
    proc = subprocess.run(f"{git_path} pull", shell=True, check=False, cwd=repo_path, timeout=300)
    if proc.returncode == 0:
        log.info("GIT pull at %s successful", repo_path, action="git_pull")
        return True
    log.warn("GIT pull at %s failed: %s", repo_path, proc.returncode, action="git_pull", stdout=proc.stdout, stderr=proc.stderr)
    return False
