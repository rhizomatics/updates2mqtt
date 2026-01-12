import datetime
from pathlib import Path

from pytest_subprocess import FakeProcess  # type: ignore[import-not-found]

from updates2mqtt.integrations.git_utils import (
    git_check_update_available,
    git_local_version,
    git_pull,
    git_timestamp,
    git_trust,
)

GIT_EXEC = Path("/usr/bin/git")


def test_git_timestamp(fake_process: FakeProcess) -> None:
    fake_process.register([fake_process.any()], stdout="""2024-04-12T00:16:33+01:00""")
    assert git_timestamp(Path("/my/path"), GIT_EXEC) == datetime.datetime(
        2024,
        4,
        12,
        0,
        16,
        33,
        0,
        datetime.timezone(offset=datetime.timedelta(hours=1)),
    )


def test_git_trust(fake_process: FakeProcess) -> None:
    fake_process.register("/usr/bin/git config --global --add safe.directory /my/path", returncode=0)
    assert git_trust(Path("/my/path"), GIT_EXEC)


def test_git_pull(fake_process: FakeProcess) -> None:
    fake_process.register("/usr/bin/git pull", returncode=0)
    assert git_pull(Path("/my/path"), GIT_EXEC)
    fake_process.register("/usr/bin/git pull", returncode=23)
    assert git_pull(Path("/my/path"), GIT_EXEC) is False


def test_git_check_update_available(fake_process: FakeProcess) -> None:
    fake_process.register(
        "/usr/bin/git fetch;/usr/bin/git status -uno",
        stdout="Your branch is behind 'origin/main' by 1 commit, and can be fast-forwarded.",
        returncode=0,
    )
    assert git_check_update_available(Path("/my/path"), GIT_EXEC) == 1
    fake_process.register(
        "/usr/bin/git fetch;/usr/bin/git status -uno", stdout="Your branch is up to date with 'origin/main'.", returncode=0
    )
    assert git_check_update_available(Path("/my/path"), GIT_EXEC) == 0
    fake_process.register("/usr/bin/git fetch;/usr/bin/git status -uno", returncode=1)
    assert git_check_update_available(Path("/my/path"), GIT_EXEC, timeout=5) == 0


def test_git_local_version(fake_process: FakeProcess) -> None:
    # Test successful case - returns git:{hash} truncated to 19 chars total
    fake_process.register(
        "/usr/bin/git rev-parse HEAD",
        stdout="abc123def456789012345678901234567890",
        returncode=0,
    )
    assert git_local_version(Path("/my/path"), GIT_EXEC) == "git:abc123def456789"


def test_git_local_version_failure(fake_process: FakeProcess) -> None:
    # Test failure case - returns None
    fake_process.register("/usr/bin/git rev-parse HEAD", returncode=128)
    assert git_local_version(Path("/my/path"), GIT_EXEC) is None
