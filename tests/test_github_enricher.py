from unittest.mock import MagicMock, Mock, patch

import pytest

from updates2mqtt.config import GitHubConfig
from updates2mqtt.integrations.docker_enrich import DockerImageInfo
from updates2mqtt.integrations.github_enrich import GithubReleaseEnricher
from updates2mqtt.model import ReleaseDetail


def make_detail(version: str | None = "1.2.3", source_repo_url: str | None = "https://github.com/org/repo") -> ReleaseDetail:
    detail = ReleaseDetail(name="test-pkg")
    detail.version = version
    detail.source_repo_url = source_repo_url
    return detail


def mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.is_success = status_code < 400
    r.json.return_value = json_data or {}
    return r


@pytest.mark.slow
def test_pkg_enricher_live() -> None:
    uut = GithubReleaseEnricher(gh_cfg=GitHubConfig(access_token="<insert_temp_token>"))  # noqa: S106
    detail = ReleaseDetail("homarr", source_repo_url="https://github.com/homarr-labs/homarr")
    uut.enrich(
        DockerImageInfo(
            "ghcr.io/homarr-labs/homarr:latest",
            image_digest="sha256:6a34b19bc9fd7f5c17d511f14b9e477424b65466084708066cb5213d62d1755b",
        ),
        detail,
    )
    assert detail.version is not None


def test_enrich_no_source_repo_url() -> None:
    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = make_detail(source_repo_url=None)
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)
    assert detail.summary is None


def test_enrich_no_version() -> None:
    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = make_detail(version=None)
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)
    assert detail.summary is None


def test_enrich_neither_version_nor_source_repo() -> None:
    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = make_detail(version=None, source_repo_url=None)
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)
    assert detail.summary is None


# === enrich() — successful tag lookup ===


@patch("updates2mqtt.integrations.github_enrich.httpx_json_content")
@patch("updates2mqtt.integrations.github_enrich.fetch_url")
def test_enrich_sets_summary_and_tag_from_release(mock_fetch: Mock, mock_json: Mock) -> None:
    payload = {"body": "Release notes body", "tag_name": "1.2.3", "reactions": {"+1": 5, "-1": 1}}
    mock_fetch.return_value = mock_response(200)
    mock_json.return_value = payload

    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = make_detail()
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)

    assert detail.summary == "Release notes body"
    assert detail.version == "1.2.3"
    assert detail.net_score == 4


@patch("updates2mqtt.integrations.github_enrich.httpx_json_content")
@patch("updates2mqtt.integrations.github_enrich.fetch_url")
def test_enrich_no_reactions_leaves_net_score_none(mock_fetch: Mock, mock_json: Mock) -> None:
    mock_fetch.return_value = mock_response(200)
    mock_json.return_value = {"body": "some notes", "tag_name": "1.2.3"}

    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = make_detail()
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)

    assert detail.summary == "some notes"
    assert detail.net_score is None


# === enrich() — 404 fallback to latest ===


@patch("updates2mqtt.integrations.github_enrich.httpx_json_content")
@patch("updates2mqtt.integrations.github_enrich.fetch_url")
def test_enrich_404_falls_back_to_latest_with_v_prefix(mock_fetch: Mock, mock_json: Mock) -> None:
    # httpx_json_content is called twice: once to match tag_name, once to extract body
    payload = {"body": "Latest notes", "tag_name": "v1.2.3", "reactions": {"+1": 0, "-1": 0}}
    mock_fetch.side_effect = [mock_response(404), mock_response(200)]
    mock_json.side_effect = [payload, payload]

    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = make_detail(version="1.2.3")
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)

    assert detail.summary == "Latest notes"
    assert detail.version == "1.2.3"


@pytest.mark.parametrize("prefix", ["v", "V", "r", "R"])
@patch("updates2mqtt.integrations.github_enrich.httpx_json_content")
@patch("updates2mqtt.integrations.github_enrich.fetch_url")
def test_enrich_404_falls_back_to_latest_with_prefix(mock_fetch: Mock, mock_json: Mock, prefix: str) -> None:
    # httpx_json_content is called twice: once to match tag_name, once to extract body
    payload = {"body": "Prefixed notes", "tag_name": f"{prefix}1.2.3"}
    mock_fetch.side_effect = [mock_response(404), mock_response(200)]
    mock_json.side_effect = [payload, payload]

    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = make_detail(version="1.2.3")
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)

    assert detail.summary == "Prefixed notes"


@patch("updates2mqtt.integrations.github_enrich.httpx_json_content")
@patch("updates2mqtt.integrations.github_enrich.fetch_url")
def test_enrich_404_latest_tag_mismatch_leaves_summary_none(mock_fetch: Mock, mock_json: Mock) -> None:
    mock_fetch.side_effect = [mock_response(404), mock_response(200)]
    mock_json.return_value = {"body": "Different version notes", "tag_name": "2.0.0"}

    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = make_detail()
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)

    assert detail.summary is None


# === enrich() — non-200/non-404 failures ===


@patch("updates2mqtt.integrations.github_enrich.httpx_json_content")
@patch("updates2mqtt.integrations.github_enrich.fetch_url")
def test_enrich_non_success_non_404_leaves_summary_none(mock_fetch: Mock, mock_json: Mock) -> None:
    mock_fetch.return_value = mock_response(403)
    mock_json.return_value = {"errors": ["forbidden"]}

    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = make_detail()
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)

    assert detail.summary is None


@patch("updates2mqtt.integrations.github_enrich.fetch_url")
def test_enrich_fetch_returns_none_leaves_summary_none(mock_fetch: Mock) -> None:
    mock_fetch.return_value = None

    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = make_detail()
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)

    assert detail.summary is None


# === diff_url fallback for summary ===


def test_enrich_diff_url_fallback_when_no_source_repo() -> None:
    """When source_repo_url is absent but diff_url is set, summary should be set from diff_url."""
    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = ReleaseDetail()
    detail.version = "1.0.0"
    detail.source_repo_url = None
    detail.diff_url = "https://github.com/org/repo/compare/v0.9.0...v1.0.0"
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)
    assert detail.as_dict()["summary"] == "<a href='https://github.com/org/repo/compare/v0.9.0...v1.0.0'>1.0.0 Diff</a>"


@patch("updates2mqtt.integrations.github_enrich.httpx_json_content")
@patch("updates2mqtt.integrations.github_enrich.fetch_url")
def test_enrich_diff_url_fallback_when_api_no_body(mock_fetch: Mock, mock_json: Mock) -> None:
    """When API returns no body field, diff_url fallback should be used."""
    mock_fetch.return_value = mock_response(200)
    mock_json.return_value = {"tag_name": "1.2.3"}  # no 'body'

    enricher = GithubReleaseEnricher(GitHubConfig())
    detail: ReleaseDetail = make_detail()
    detail.diff_url = "https://github.com/org/repo/compare/v1.0.0...v1.2.3"
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)

    assert detail.as_dict()["summary"] == "<a href='https://github.com/org/repo/compare/v1.0.0...v1.2.3'>1.2.3 Diff</a>"


# === URL construction ===


@patch("updates2mqtt.integrations.github_enrich.httpx_json_content")
@patch("updates2mqtt.integrations.github_enrich.fetch_url")
def test_enrich_api_url_uses_source_repo_url(mock_fetch: Mock, mock_json: Mock) -> None:
    """API URL should replace github.com with api.github.com/repos."""
    mock_fetch.return_value = mock_response(200)
    mock_json.return_value = {"body": "notes", "tag_name": "3.0.0"}

    enricher = GithubReleaseEnricher(GitHubConfig())
    detail = ReleaseDetail(name="myrepo")
    detail.version = "3.0.0"
    detail.source_repo_url = "https://github.com/myorg/myrepo"
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)

    mock_fetch.assert_called_once_with(
        "https://api.github.com/repos/myorg/myrepo/releases/tags/3.0.0",
        bearer_token=None,
        cache_ttl=54000,
        allow_stale=True,
    )
    assert detail.summary == "notes"


# === Bearer token forwarding ===


@patch("updates2mqtt.integrations.github_enrich.httpx_json_content")
@patch("updates2mqtt.integrations.github_enrich.fetch_url")
def test_enrich_passes_bearer_token(mock_fetch: Mock, mock_json: Mock) -> None:
    mock_fetch.return_value = mock_response(200)
    mock_json.return_value = {"body": "authed notes", "tag_name": "1.2.3"}

    enricher = GithubReleaseEnricher(GitHubConfig(access_token="ghp_secret"))  # noqa: S106
    detail = make_detail()
    enricher.enrich(DockerImageInfo("ghcr.io/example-labs/example", image_digest="sha256:fake0123456789abcedf"), detail)

    mock_fetch.assert_called_once_with(
        "https://api.github.com/repos/org/repo/releases/tags/1.2.3",
        bearer_token="ghp_secret",  # noqa: S106
        cache_ttl=54000,
        allow_stale=True,
    )
