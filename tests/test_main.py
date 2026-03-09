from __future__ import annotations

import json
import tomllib
from pathlib import Path

import httpx
import pytest

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
def reset_config() -> None:
    previous = server_main.config
    server_main.config = make_config()
    yield
    server_main.config = previous


def test_server_config_normalizes_base_urls() -> None:
    config = make_config()

    assert config.radarr_url == "http://radarr.local"
    assert config.sonarr_url == "http://sonarr.local"


@pytest.mark.asyncio
async def test_search_and_add_show_auto_add_does_not_pass_tmdb_id_as_root_folder(
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
        return AddMediaResponse(success=True, message="ok")

    monkeypatch.setattr(MediaServerAPI, "search_sonarr_shows", fake_search)
    monkeypatch.setattr(MediaServerAPI, "add_series_to_sonarr", fake_add)

    results = await server_main.search_and_add_show("British time travel show", auto_add=True)

    assert len(results) == 1
    assert results[0].overview == "No overview available"
    assert captured == {
        "tvdb_id": 78804,
        "title": "Doctor Who",
        "root_folder": None,
    }


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
async def test_media_server_api_closes_owned_client(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = False

    async def fake_aclose(self: httpx.AsyncClient) -> None:
        nonlocal closed
        closed = True

    monkeypatch.setattr(httpx.AsyncClient, "aclose", fake_aclose)

    async with MediaServerAPI(make_config()):
        pass

    assert closed is True


def test_get_int_env_falls_back_for_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALITY_PROFILE_ID", "not-a-number")

    assert server_main._get_int_env("QUALITY_PROFILE_ID", 7) == 7


@pytest.mark.asyncio
async def test_add_movie_to_radarr_skips_invalid_root_folder_entries() -> None:
    requests_seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        if request.url.path.endswith("/rootfolder"):
            return httpx.Response(200, json=[{"path": ""}, {"path": "/movies"}], request=request)
        if request.url.path.endswith("/movie"):
            return httpx.Response(201, json={"id": 42}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        api = MediaServerAPI(make_config(), client=client)
        result = await api.add_movie_to_radarr(603, "The Matrix")

    assert result.success is True
    payload = json.loads(requests_seen[-1].content.decode())
    assert payload["rootFolderPath"] == "/movies"


@pytest.mark.asyncio
async def test_add_series_to_sonarr_surfaces_api_error_message() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rootfolder"):
            return httpx.Response(200, json=[], request=request)
        if request.url.path.endswith("/series"):
            return httpx.Response(
                400,
                json=[{"errorMessage": "Series already exists"}],
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        api = MediaServerAPI(make_config(), client=client)
        result = await api.add_series_to_sonarr(78804, "Doctor Who")

    assert result.success is False
    assert result.message == "Failed to add series: Series already exists"


@pytest.mark.asyncio
async def test_search_and_add_show_requires_sonarr_api_key() -> None:
    server_main.config = make_config()
    server_main.config.sonarr_api_key = ""

    with pytest.raises(ValueError, match="Sonarr API key not configured"):
        await server_main.search_and_add_show("Doctor Who")


@pytest.mark.asyncio
async def test_get_server_status_uses_utc_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_check_radarr(self: MediaServerAPI) -> dict[str, object]:
        return {"status": "connected", "data": {"version": "5.0.0"}}

    async def fake_check_sonarr(self: MediaServerAPI) -> dict[str, object]:
        return {"status": "connected", "data": {"version": "4.0.0"}}

    monkeypatch.setattr(MediaServerAPI, "check_radarr_status", fake_check_radarr)
    monkeypatch.setattr(MediaServerAPI, "check_sonarr_status", fake_check_sonarr)

    result = await server_main.get_server_status()

    assert result["timestamp"].endswith("+00:00")


def test_version_metadata_stays_in_sync() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    manifest = json.loads((repo_root / "manifest.json").read_text())

    assert pyproject["project"]["version"] == __version__
    assert manifest["version"] == __version__
