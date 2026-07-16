from __future__ import annotations

import json
import tomllib
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from arr_assistant_mcp import __version__
from arr_assistant_mcp import main as server_main
from arr_assistant_mcp.main import AddMediaResponse, MediaServerAPI, ServerConfig


def make_config() -> ServerConfig:
    return ServerConfig(
        radarr_url="http://radarr.local/",
        radarr_api_key="radarr-key",
        sonarr_url="http://sonarr.local/",
        sonarr_api_key="sonarr-key",
        quality_profile_id=1,
    )


@pytest.fixture(autouse=True)
def reset_config() -> Generator[None, None, None]:
    previous = server_main.config
    server_main.config = make_config()
    yield
    server_main.config = previous


def test_server_config_normalizes_base_urls() -> None:
    config = make_config()

    assert config.radarr_url == "http://radarr.local"
    assert config.sonarr_url == "http://sonarr.local"


@pytest.mark.asyncio
async def test_search_and_add_show_returns_explicit_failed_add_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_search(self: MediaServerAPI, query: str) -> list[dict[str, object]]:
        return [
            {
                "title": "Doctor Who",
                "year": 2005,
                "overview": None,
                "tmdbId": 57243,
                "tvdbId": 78804,
                "remotePoster": "https://example.com/poster.jpg",
            }
        ]

    async def fake_add(
        self: MediaServerAPI,
        tvdb_id: int,
        title: str,
        root_folder: str | None = None,
    ) -> AddMediaResponse:
        captured["tvdb_id"] = tvdb_id
        captured["title"] = title
        captured["root_folder"] = root_folder
        return AddMediaResponse(success=False, message="simulated Sonarr failure")

    monkeypatch.setattr(MediaServerAPI, "search_sonarr_shows", fake_search)
    monkeypatch.setattr(MediaServerAPI, "add_series_to_sonarr", fake_add)

    response = await server_main.search_and_add_show(
        "British time travel show",
        auto_add=True,
    )

    assert len(response.results) == 1
    assert response.results[0].overview == "No overview available"
    assert response.auto_add_requested is True
    assert response.auto_add_result == AddMediaResponse(
        success=False,
        message="simulated Sonarr failure",
    )
    assert captured == {
        "tvdb_id": 78804,
        "title": "Doctor Who",
        "root_folder": None,
    }


@pytest.mark.asyncio
async def test_search_and_add_show_reports_when_auto_add_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(self: MediaServerAPI, query: str) -> list[dict[str, object]]:
        return [
            {"title": "Doctor Who", "overview": "One", "tvdbId": 78804},
            {"title": "Doctor Who Classic", "overview": "Two", "tvdbId": 76107},
        ]

    monkeypatch.setattr(MediaServerAPI, "search_sonarr_shows", fake_search)

    response = await server_main.search_and_add_show("Doctor Who", auto_add=True)

    assert len(response.results) == 2
    assert response.auto_add_result is not None
    assert response.auto_add_result.success is False
    assert response.auto_add_result.message == "Auto-add requires exactly one result; found 2"


@pytest.mark.asyncio
async def test_search_and_add_show_requires_sonarr_api_key() -> None:
    assert server_main.config is not None
    server_main.config.sonarr_api_key = ""

    with pytest.raises(ValueError, match="Sonarr API key not configured"):
        await server_main.search_and_add_show("Doctor Who")

    with pytest.raises(ValueError, match="Sonarr API key not configured"):
        await server_main.add_show_by_tvdb_id(78804, "Doctor Who")


@pytest.mark.asyncio
async def test_add_movie_requires_radarr_api_key() -> None:
    assert server_main.config is not None
    server_main.config.radarr_api_key = ""

    with pytest.raises(ValueError, match="Radarr API key not configured"):
        await server_main.add_movie_by_id(603)


@pytest.mark.asyncio
async def test_test_config_checks_both_services(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_check_radarr(self: MediaServerAPI) -> dict[str, object]:
        return {"status": "connected", "data": {"version": "5.0.0"}}

    async def fake_check_sonarr(self: MediaServerAPI) -> dict[str, object]:
        return {"status": "error", "message": "connection refused"}

    monkeypatch.setattr(MediaServerAPI, "check_radarr_status", fake_check_radarr)
    monkeypatch.setattr(MediaServerAPI, "check_sonarr_status", fake_check_sonarr)

    result = await server_main.test_config()

    assert result["radarr_connectivity"] == "connected"
    assert result["radarr_version"] == "5.0.0"
    assert result["sonarr_connectivity"] == "error"
    assert result["sonarr_error"] == "connection refused"


@pytest.mark.asyncio
async def test_media_server_api_closes_owned_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed = False

    async def fake_aclose(self: httpx.AsyncClient) -> None:
        nonlocal closed
        closed = True

    monkeypatch.setattr(httpx.AsyncClient, "aclose", fake_aclose)

    async with MediaServerAPI(make_config()):
        pass

    assert closed is True


@pytest.mark.asyncio
async def test_add_movie_skips_invalid_root_folder_entries() -> None:
    requests_seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        if request.url.path.endswith("/rootfolder"):
            return httpx.Response(
                200,
                json=[{}, {"path": ""}, {"path": "/movies"}],
                request=request,
            )
        if request.url.path.endswith("/movie"):
            return httpx.Response(201, json={"id": 42}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        api = MediaServerAPI(make_config(), client=client)
        result = await api.add_movie_to_radarr(603, "The Matrix")

    assert result == AddMediaResponse(
        success=True,
        message="Successfully added 'The Matrix' to Radarr",
        media_id=42,
    )
    payload = json.loads(requests_seen[-1].content.decode())
    assert payload["rootFolderPath"] == "/movies"


@pytest.mark.asyncio
async def test_add_movie_fails_cleanly_without_valid_root_folder() -> None:
    post_attempted = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_attempted
        if request.url.path.endswith("/rootfolder"):
            return httpx.Response(200, json=[{}, {"path": " "}], request=request)
        post_attempted = True
        return httpx.Response(500, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        api = MediaServerAPI(make_config(), client=client)
        result = await api.add_movie_to_radarr(603, "The Matrix")

    assert result == AddMediaResponse(
        success=False,
        message="No valid Radarr root folder is configured or available",
    )
    assert post_attempted is False


@pytest.mark.asyncio
async def test_add_series_surfaces_arr_error_message() -> None:
    config = make_config()
    config.sonarr_root_folder = "/shows"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json=[{"errorMessage": "Series already exists"}],
            request=request,
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        api = MediaServerAPI(config, client=client)
        result = await api.add_series_to_sonarr(78804, "Doctor Who")

    assert result == AddMediaResponse(
        success=False,
        message="Failed to add series: Series already exists",
    )


@pytest.mark.asyncio
async def test_get_server_status_uses_utc_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_check_radarr(self: MediaServerAPI) -> dict[str, object]:
        return {"status": "connected", "data": {"version": "5.0.0"}}

    async def fake_check_sonarr(self: MediaServerAPI) -> dict[str, object]:
        return {"status": "connected", "data": {"version": "4.0.0"}}

    monkeypatch.setattr(MediaServerAPI, "check_radarr_status", fake_check_radarr)
    monkeypatch.setattr(MediaServerAPI, "check_sonarr_status", fake_check_sonarr)

    result = await server_main.get_server_status()

    assert result["timestamp"].endswith("+00:00")


@pytest.mark.asyncio
async def test_mcp_server_exposes_expected_tools() -> None:
    async with Client(server_main.mcp) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools} == {
        "add_movie_by_id",
        "add_show_by_tvdb_id",
        "get_server_status",
        "search_and_add_show",
        "search_movies",
        "test_config",
    }


def test_get_int_env_falls_back_for_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUALITY_PROFILE_ID", "not-a-number")

    assert server_main._get_int_env("QUALITY_PROFILE_ID", 7) == 7


def test_version_metadata_stays_in_sync() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    manifest = json.loads((repo_root / "manifest.json").read_text())

    assert pyproject["project"]["version"] == __version__
    assert manifest["version"] == __version__
