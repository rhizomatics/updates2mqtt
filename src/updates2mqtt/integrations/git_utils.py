import datetime
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from re import Match

import structlog

from updates2mqtt.helpers import ProcessResult, run_process

log = structlog.get_logger()

GIT_PULL_TIMEOUT = 300
GIT_LOCAL_TIMEOUT = 30
# Repo paths come from container settings, and the repo's own config is read by every git command,
# so switch off the config driven ways of running a program that these commands could reach.
# Command line config takes precedence over the repo's. Defence in depth, not a complete list.
GIT_HARDENING: tuple[str, ...] = (
    "protocol.ext.allow=never",
    "core.fsmonitor=false",
    "core.hooksPath=/dev/null",
)


def git_command(git_path: Path, repo_path: Path, *args: str) -> list[str]:
    """Argument list for a git command in a repo, never a shell string, as the path isn't trusted

    The repo is marked safe for this command only, rather than in the global git config, since it's
    usually owned by a different user to the one Updates2MQTT runs as
    """
    cmd: list[str] = [str(git_path), "-c", f"safe.directory={repo_path.resolve()}"]
    for setting in GIT_HARDENING:
        cmd.extend(("-c", setting))
    cmd.extend(args)
    return cmd


def git_repo_allowed(repo_path: Path, roots: Sequence[str] | None) -> bool:
    """Whether a repo is inside one of the allowed root directories, any repo being allowed if none are set"""
    if not roots:
        return True
    try:
        resolved: Path = repo_path.resolve()
        return any(resolved.is_relative_to(Path(root).resolve()) for root in roots)
    except (OSError, ValueError) as e:
        log.warning("GIT Unable to check repo path %s: %s", repo_path, e, action="git_repo_allowed")
        return False


def git_iso_timestamp(repo_path: Path, git_path: Path) -> str | None:
    result = None
    try:
        # argument list from git_command, never a shell, with only the repo path coming from configuration
        result = subprocess.run(  # nosec B603
            git_command(git_path, repo_path, "log", "-1", "--format=%cI", "--no-show-signature"),
            cwd=repo_path,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=True,
            timeout=GIT_LOCAL_TIMEOUT,
        )
        # round-trip the iso format for pythony consistency
        return datetime.datetime.fromisoformat(result.stdout.strip()).isoformat()
    except subprocess.CalledProcessError as cpe:
        log.warning("GIT No result from git log at %s: %s", repo_path, cpe, action="git_iso_timestamp")
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
        # argument list from git_command, never a shell, with only the repo path coming from configuration
        result = subprocess.run(  # nosec B603
            git_command(git_path, repo_path, "rev-parse", "HEAD"),
            cwd=repo_path,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=True,
            timeout=GIT_LOCAL_TIMEOUT,
        )
        if result.returncode == 0:
            log.debug("Local git rev-parse", action="git_local_digest", path=repo_path, version=result.stdout.strip())
            return result.stdout.strip()[:15]
    except subprocess.CalledProcessError as cpe:
        log.warning("GIT No result from git rev-parse at %s: %s", repo_path, cpe, action="git_local_digest")
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
        # check if remote repo ahead, status is still worth having if the fetch fails, e.g. when offline
        fetched = subprocess.run(  # nosec B603
            git_command(git_path, repo_path, "fetch"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            cwd=repo_path,
            timeout=timeout,
        )
        if fetched.returncode != 0:
            log.debug("GIT fetch failed", action="git_check", path=repo_path, returncode=fetched.returncode)
        # argument list from git_command, never a shell, with only the repo path coming from configuration
        result = subprocess.run(  # nosec B603
            git_command(git_path, repo_path, "status", "-uno"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
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
        log.warning("GIT Unable to check status %s: %s", result.stdout if result else "<NO RESULT>", e, action="git_check")
    return 0


async def git_pull(repo_path: Path, git_path: Path) -> bool:
    log.info("GIT Pulling git at %s", repo_path, action="git_pull")
    result: ProcessResult = await run_process(git_command(git_path, repo_path, "pull"), cwd=repo_path, timeout=GIT_PULL_TIMEOUT)
    if result.ok:
        log.info("GIT pull at %s successful", repo_path, action="git_pull")
        return True
    log.warning(
        "GIT pull at %s failed: %s",
        repo_path,
        result.returncode,
        action="git_pull",
        stdout=result.stdout,
        stderr=result.stderr,
    )
    return False
