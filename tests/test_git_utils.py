from pathlib import Path

from pytest_subprocess import FakeProcess  # type: ignore[import-not-found]

from updates2mqtt.integrations.git_utils import (
    git_check_update_available,
    git_iso_timestamp,
    git_local_version,
    git_pull,
    git_trust,
)

GIT_EXEC = Path("/usr/bin/git")


def test_git_iso_timestamp(fake_process: FakeProcess) -> None:
    fake_process.register([fake_process.any()], stdout="""2024-04-12T00:16:33+01:00""")
    assert git_iso_timestamp(Path("/my/path"), GIT_EXEC) == "2024-04-12T00:16:33+01:00"


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
        stdout="""On branch main\nYour branch is behind \'origin/main\' by 1 commit, and can be fast-forwarded.\n  (use "git pull" to update your local branch)\n\nnothing to commit (use -u to show untracked files)""",  # noqa: E501
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
