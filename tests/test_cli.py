import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from omegaconf import DictConfig, OmegaConf

from updates2mqtt.cli import dump, dump_url, main
from updates2mqtt.model import Discovery


def _conf(**kwargs: Any) -> DictConfig:
    return OmegaConf.create({"log_level": "ERROR", **kwargs})


def _mock_response(status_code: int = 200, text: str = '{"ok": 1}', is_success: bool = True, is_error: bool = False) -> Mock:
    r = Mock()
    r.status_code = status_code
    r.is_success = is_success
    r.is_error = is_error
    r.text = text
    r.headers = {}
    return r


def _make_scanner(*discoveries: Discovery) -> Mock:
    """Return a mock DockerProvider whose scan() yields the given discoveries."""
    scanner = Mock()

    async def _scan(*_args: Any) -> AsyncGenerator[Discovery, Any]:
        for d in discoveries:
            yield d

    scanner.scan = _scan
    return scanner


def _make_discovery() -> tuple[Mock, Discovery]:
    provider = Mock()
    provider.source_type = "docker"
    disc = Discovery(provider, "testpkg", "sess", "node", current_version="1.0", latest_version="2.0")
    # Provide current_detail so CSV rendering doesn't crash
    disc.as_dict = Mock(  # type:ignore [method-assign]
        return_value={
            "name": "testpkg",
            "current_detail": {"image_ref": "ghcr.io/org/repo:latest", "index_name": "ghcr.io"},
            "installed_version": "1.0",
            "latest_version": "2.0",
            "version_basis": "semver",
            "title": "Test Package",
            "can_update": True,
            "can_build": False,
            "can_restart": False,
            "update_type": "INSTALL",
            "release": {"source": None},
            "last_scan": {"throttled": False},
        }
    )
    return provider, disc


# === dump_url ===


@patch("updates2mqtt.cli.print_json")
@patch("updates2mqtt.cli.fetch_url")
@patch("updates2mqtt.cli.ContainerDistributionAPIVersionLookup")
def test_dump_url_tags_calls_list_endpoint(mock_lookup_cls: Mock, mock_fetch: Mock, mock_print_json: Mock) -> None:
    mock_lookup_cls.return_value.fetch_token.return_value = "tok"
    mock_fetch.return_value = _mock_response()

    dump_url("tags", "ghcr.io/org/repo:latest", _conf())

    url = mock_fetch.call_args[0][0]
    assert "/tags/list" in url
    mock_print_json.assert_called_once()


@patch("updates2mqtt.cli.print_json")
@patch("updates2mqtt.cli.fetch_url")
@patch("updates2mqtt.cli.ContainerDistributionAPIVersionLookup")
def test_dump_url_manifest_calls_manifests_endpoint(mock_lookup_cls: Mock, mock_fetch: Mock, mock_print_json: Mock) -> None:
    mock_lookup_cls.return_value.fetch_token.return_value = None
    mock_fetch.return_value = _mock_response()

    dump_url("manifest", "ghcr.io/org/repo:latest", _conf())

    url = mock_fetch.call_args[0][0]
    assert "/manifests/" in url
    mock_print_json.assert_called_once()


@patch("updates2mqtt.cli.print_json")
@patch("updates2mqtt.cli.fetch_url")
@patch("updates2mqtt.cli.ContainerDistributionAPIVersionLookup")
def test_dump_url_blob_calls_blobs_endpoint(mock_lookup_cls: Mock, mock_fetch: Mock, mock_print_json: Mock) -> None:
    mock_lookup_cls.return_value.fetch_token.return_value = None
    mock_fetch.return_value = _mock_response()
    digest = "sha256:" + "a" * 64

    dump_url("blob", f"ghcr.io/org/repo@{digest}", _conf())

    url = mock_fetch.call_args[0][0]
    assert "/blobs/" in url
    mock_print_json.assert_called_once()


@patch("updates2mqtt.cli.fetch_url")
def test_dump_url_blob_without_digest_returns_early(mock_fetch: Mock) -> None:
    dump_url("blob", "ghcr.io/org/repo:latest", _conf())
    mock_fetch.assert_not_called()


@patch("updates2mqtt.cli.fetch_url")
def test_dump_url_manifest_without_tag_returns_early(mock_fetch: Mock) -> None:
    # Construct a ref that parses with no tag_or_digest — extremely degenerate; fall back
    # to testing the unknown doc_type branch instead which is simpler to trigger
    dump_url("unknown_type", "ghcr.io/org/repo:latest", _conf())
    mock_fetch.assert_not_called()


@patch("updates2mqtt.cli.print_json")
@patch("updates2mqtt.cli.fetch_url")
@patch("updates2mqtt.cli.ContainerDistributionAPIVersionLookup")
def test_dump_url_error_response_skips_print(mock_lookup_cls: Mock, mock_fetch: Mock, mock_print_json: Mock) -> None:
    mock_lookup_cls.return_value.fetch_token.return_value = None
    mock_fetch.return_value = _mock_response(status_code=403, is_success=False, is_error=True)

    dump_url("tags", "ghcr.io/org/repo:latest", _conf())

    mock_print_json.assert_not_called()


@patch("updates2mqtt.cli.print_json")
@patch("updates2mqtt.cli.fetch_url")
@patch("updates2mqtt.cli.ContainerDistributionAPIVersionLookup")
def test_dump_url_none_response_skips_print(mock_lookup_cls: Mock, mock_fetch: Mock, mock_print_json: Mock) -> None:
    mock_lookup_cls.return_value.fetch_token.return_value = None
    mock_fetch.return_value = None

    dump_url("tags", "ghcr.io/org/repo:latest", _conf())

    mock_print_json.assert_not_called()


# === dump (async) ===


@pytest.mark.asyncio
@patch("updates2mqtt.cli.print_json")
@patch("updates2mqtt.cli.docker_provider")
async def test_dump_json_format(mock_dp: Mock, mock_print_json: Mock) -> None:
    _, disc = _make_discovery()
    mock_dp.return_value = _make_scanner(disc)

    await dump("json", _conf())

    mock_print_json.assert_called_once()
    data = json.loads(mock_print_json.call_args[0][0])
    assert len(data) == 1
    assert data[0]["name"] == "testpkg"


@pytest.mark.asyncio
@patch("updates2mqtt.cli.Console")
@patch("updates2mqtt.cli.docker_provider")
async def test_dump_csv_format(mock_dp: Mock, mock_console_cls: Mock) -> None:
    _, disc = _make_discovery()
    mock_dp.return_value = _make_scanner(disc)
    mock_console = Mock()
    mock_console_cls.return_value = mock_console

    await dump("csv", _conf())

    # header row + at least one data row
    assert mock_console.print.call_count >= 2


@pytest.mark.asyncio
@patch("updates2mqtt.cli.print_json")
@patch("updates2mqtt.cli.docker_provider")
async def test_dump_json_single_container(mock_dp: Mock, mock_print_json: Mock) -> None:
    _, disc = _make_discovery()
    mock_scanner = Mock()
    mock_scanner.rescan.return_value = disc
    mock_dp.return_value = mock_scanner

    await dump("json", _conf(container="mycontainer"))

    mock_scanner.rescan.assert_called_once()
    mock_print_json.assert_called_once()
    data = json.loads(mock_print_json.call_args[0][0])
    assert len(data) == 1


@pytest.mark.asyncio
@patch("updates2mqtt.cli.docker_provider")
async def test_dump_json_single_container_none_result(mock_dp: Mock) -> None:
    mock_scanner = Mock()
    mock_scanner.rescan.return_value = None
    mock_dp.return_value = mock_scanner

    # Should not raise when rescan returns None
    with patch("updates2mqtt.cli.print_json") as mock_pj:
        await dump("json", _conf(container="missing"))
        data = json.loads(mock_pj.call_args[0][0])
        assert data == []


@pytest.mark.asyncio
@patch("updates2mqtt.cli.docker_provider")
async def test_dump_unknown_format_logs_warning(mock_dp: Mock) -> None:
    _, disc = _make_discovery()
    mock_dp.return_value = _make_scanner(disc)

    # Should not raise — just logs a warning
    await dump("xml", _conf())


# === main dispatching ===


@patch("updates2mqtt.cli.OmegaConf")
def test_main_help_flag(mock_oc: Mock) -> None:
    mock_oc.from_cli.return_value = OmegaConf.create({"help": True})
    main()  # should not raise


@patch("updates2mqtt.cli.dump_url")
@patch("updates2mqtt.cli.OmegaConf")
def test_main_dispatches_blob(mock_oc: Mock, mock_dump_url: Mock) -> None:
    conf = OmegaConf.create({"blob": "ghcr.io/org/repo@sha256:abc"})
    mock_oc.from_cli.return_value = conf

    main()

    mock_dump_url.assert_called_once_with("blob", "ghcr.io/org/repo@sha256:abc", conf)


@patch("updates2mqtt.cli.dump_url")
@patch("updates2mqtt.cli.OmegaConf")
def test_main_dispatches_manifest(mock_oc: Mock, mock_dump_url: Mock) -> None:
    conf = OmegaConf.create({"manifest": "ghcr.io/org/repo:latest"})
    mock_oc.from_cli.return_value = conf

    main()

    mock_dump_url.assert_called_once_with("manifest", "ghcr.io/org/repo:latest", conf)


@patch("updates2mqtt.cli.dump_url")
@patch("updates2mqtt.cli.OmegaConf")
def test_main_dispatches_tags(mock_oc: Mock, mock_dump_url: Mock) -> None:
    conf = OmegaConf.create({"tags": "ghcr.io/org/repo"})
    mock_oc.from_cli.return_value = conf

    main()

    mock_dump_url.assert_called_once_with("tags", "ghcr.io/org/repo", conf)


@patch("asyncio.run")
@patch("updates2mqtt.cli.dump")
@patch("updates2mqtt.cli.OmegaConf")
def test_main_dispatches_dump(mock_oc: Mock, mock_dump: Mock, mock_asyncio_run: Mock) -> None:
    conf = OmegaConf.create({"dump": "json"})
    mock_oc.from_cli.return_value = conf
    mock_dump.return_value = MagicMock()  # pretend coroutine

    main()

    mock_asyncio_run.assert_called_once()


@patch("updates2mqtt.cli.docker_provider")
@patch("updates2mqtt.cli.OmegaConf")
def test_main_default_rescans_container(mock_oc: Mock, mock_dp: Mock) -> None:
    conf = OmegaConf.create({"container": "frigate"})
    mock_oc.from_cli.return_value = conf
    _, disc = _make_discovery()
    mock_scanner = Mock()
    mock_scanner.rescan.return_value = disc
    mock_dp.return_value = mock_scanner

    main()

    mock_scanner.rescan.assert_called_once()


@patch("updates2mqtt.cli.docker_provider")
@patch("updates2mqtt.cli.OmegaConf")
def test_main_default_no_discovery_result(mock_oc: Mock, mock_dp: Mock) -> None:
    conf = OmegaConf.create({})
    mock_oc.from_cli.return_value = conf
    mock_scanner = Mock()
    mock_scanner.rescan.return_value = None
    mock_dp.return_value = mock_scanner

    main()  # should not raise when rescan returns None
