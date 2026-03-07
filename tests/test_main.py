from __future__ import annotations

import httpx
import pytest

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
async def test_search_and_add_show_auto_add_does_not_pass_tmdb_id_as_root_folder(monkeypatch: pytest.MonkeyPatch) -> None:
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
