from __future__ import annotations

import gzip
import json
import logging
import tomllib
from collections.abc import AsyncIterator, Generator
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from arr_assistant_mcp import __version__
from arr_assistant_mcp import main as server_main
from arr_assistant_mcp.main import (
    AddMediaResponse,
    ArrResponseTooLargeError,
    MediaServerAPI,
    ServerConfig,
)


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


@pytest.mark.parametrize(
    ("url", "should_warn"),
    [
        ("http://localhost:7878", False),
        ("http://radarr.localhost:7878", False),
        ("http://127.0.0.1:7878", False),
        ("http://[::1]:7878", False),
        ("https://radarr.example.com", False),
        ("http://192.168.1.11:7878", True),
        ("http://radarr.internal:7878", True),
    ],
)
def test_server_config_warns_for_non_loopback_plaintext_http(
    url: str,
    should_warn: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=server_main.__name__)

    ServerConfig(
        radarr_url=url,
        radarr_api_key="secret-api-key",
        sonarr_url="https://sonarr.example.com",
        sonarr_api_key="another-secret",
    )

    warnings = [record.getMessage() for record in caplog.records]
    assert bool(warnings) is should_warn
    assert all("secret-api-key" not in warning for warning in warnings)
    assert all("another-secret" not in warning for warning in warnings)
    if should_warn:
        assert warnings == [
            f"Radarr API credentials will be sent over plaintext HTTP to "
            f"{url}; use HTTPS or a trusted private network"
        ]


def test_server_config_warns_once_for_each_plaintext_service(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=server_main.__name__)

    ServerConfig(
        radarr_url="http://radarr.internal:7878",
        radarr_api_key="radarr-key",
        sonarr_url="http://sonarr.internal:8989",
        sonarr_api_key="sonarr-key",
    )

    assert [record.getMessage() for record in caplog.records] == [
        "Radarr API credentials will be sent over plaintext HTTP to "
        "http://radarr.internal:7878; use HTTPS or a trusted private network",
        "Sonarr API credentials will be sent over plaintext HTTP to "
        "http://sonarr.internal:8989; use HTTPS or a trusted private network",
    ]


class TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize("payload", [b"1234", b"12345678"])
@pytest.mark.asyncio
async def test_bounded_reader_accepts_payloads_through_exact_limit_and_closes_response(
    payload: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_main, "MAX_RESPONSE_BYTES", 8)
    stream = TrackingStream([payload])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = MediaServerAPI(make_config(), client=client)
        response = await api._request("Radarr", "GET", "http://radarr.local/test")

    assert response.content == payload
    assert stream.closed is True


@pytest.mark.asyncio
async def test_bounded_reader_rejects_chunked_overflow_and_closes_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_main, "MAX_RESPONSE_BYTES", 8)
    stream = TrackingStream([b"1234", b"5678", b"9"])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = MediaServerAPI(make_config(), client=client)
        with pytest.raises(ArrResponseTooLargeError, match="Radarr response exceeded"):
            await api._request("Radarr", "GET", "http://radarr.local/test")

    assert stream.closed is True


@pytest.mark.asyncio
async def test_bounded_reader_limits_decoded_compressed_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_main, "MAX_RESPONSE_BYTES", 8)
    compressed = gzip.compress(b"123456789")
    stream = TrackingStream([compressed])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=stream,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = MediaServerAPI(make_config(), client=client)
        with pytest.raises(ArrResponseTooLargeError, match="Radarr response exceeded"):
            await api._request("Radarr", "GET", "http://radarr.local/test")

    assert stream.closed is True


@pytest.mark.asyncio
async def test_all_arr_response_paths_enforce_shared_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_main, "MAX_RESPONSE_BYTES", 8)
    config = make_config()
    config.radarr_root_folder = "/movies"
    config.sonarr_root_folder = "/shows"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"123456789", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = MediaServerAPI(config, client=client)

        assert await api.get_radarr_root_folders() == []
        assert await api.get_sonarr_root_folders() == []

        with pytest.raises(ArrResponseTooLargeError):
            await api.search_radarr_movies("Matrix")
        with pytest.raises(ArrResponseTooLargeError):
            await api.search_sonarr_shows("Doctor Who")

        movie_result = await api.add_movie_to_radarr(603, "The Matrix")
        show_result = await api.add_series_to_sonarr(78804, "Doctor Who")
        assert movie_result.success is False
        assert "exceeded the" in movie_result.message
        assert show_result.success is False
        assert "exceeded the" in show_result.message

        radarr_status = await api.check_radarr_status()
        sonarr_status = await api.check_sonarr_status()
        assert radarr_status["status"] == "error"
        assert "exceeded the" in radarr_status["message"]
        assert sonarr_status["status"] == "error"
        assert "exceeded the" in sonarr_status["message"]


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
