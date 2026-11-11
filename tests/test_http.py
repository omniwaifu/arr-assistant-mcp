"""HTTP entry-point and real-wire MCP tests; never contact Arr services."""

import asyncio
import os
import socket
import sys
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastmcp import Client

from arr_assistant_mcp import main as server

TOKEN = "test-token-" + "a" * 48


@pytest.fixture(autouse=True)
def clean_runtime_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in os.environ:
        if name.startswith("ARR_MCP_"):
            monkeypatch.delenv(name)
    previous_auth, previous_config = server.mcp.auth, server.config
    yield
    server.mcp.auth, server.config = previous_auth, previous_config


@pytest.mark.parametrize("token", ["", "short", "a" * 32 + "\n", "é" * 32, "a" * 32 + "\x00"])
def test_http_refuses_missing_or_invalid_token(monkeypatch: pytest.MonkeyPatch, token: str) -> None:
    monkeypatch.setenv("ARR_MCP_TRANSPORT", "http")
    # NUL cannot be set in an OS environment; emulate a malformed caller's environment.
    original_getenv = os.getenv
    monkeypatch.setattr(
        server.os,
        "getenv",
        lambda name, default=None: (
            token if name == "ARR_MCP_TOKEN" else original_getenv(name, default)
        ),
    )
    with pytest.raises(SystemExit, match="HTTP requires ARR_MCP_TOKEN"):
        server.main()


@pytest.mark.parametrize("port", ["0", "65536", "nonsense", ""])
def test_http_refuses_invalid_port(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("ARR_MCP_TRANSPORT", "http")
    monkeypatch.setenv("ARR_MCP_TOKEN", TOKEN)
    monkeypatch.setenv("ARR_MCP_PORT", port)
    with pytest.raises(SystemExit, match="ARR_MCP_PORT"):
        server.main()


def test_refuses_unknown_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARR_MCP_TRANSPORT", "udp")
    with pytest.raises(SystemExit, match="ARR_MCP_TRANSPORT"):
        server.main()


def test_stdio_remains_default_and_ignores_http_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARR_MCP_PORT", "invalid")
    monkeypatch.setenv("ARR_MCP_TOKEN", "short")
    calls = []
    monkeypatch.setattr(server.mcp, "run", lambda **kwargs: calls.append(kwargs))

    server.main()

    assert calls == [{"transport": "stdio"}]
    assert server.config is not None


def test_http_refuses_empty_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARR_MCP_TRANSPORT", "http")
    monkeypatch.setenv("ARR_MCP_TOKEN", TOKEN)
    monkeypatch.setenv("ARR_MCP_HOST", " ")
    with pytest.raises(SystemExit, match="ARR_MCP_HOST"):
        server.main()


@pytest.mark.asyncio
async def test_http_startup_applies_auth_and_deployment_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARR_MCP_TRANSPORT", "http")
    monkeypatch.setenv("ARR_MCP_TOKEN", TOKEN)
    monkeypatch.setenv("ARR_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("ARR_MCP_PORT", "8123")
    monkeypatch.setenv("ARR_MCP_ALLOWED_HOSTS", " media.example.com, 192.168.1.50, ")
    calls = []
    monkeypatch.setattr(server.mcp, "run", lambda **kwargs: calls.append(kwargs))

    server.main()

    assert calls == [
        {
            "transport": "http",
            "host": "0.0.0.0",
            "port": 8123,
            "path": "/mcp",
            "stateless_http": True,
            "json_response": True,
            "host_origin_protection": True,
            "allowed_hosts": ["media.example.com", "192.168.1.50"],
        }
    ]
    assert server.mcp.auth is not None
    assert await server.mcp.auth.verify_token(TOKEN) is not None
    assert await server.mcp.auth.verify_token("wrong") is None
    assert TOKEN not in repr(vars(server.mcp.auth))


@pytest.fixture
async def http_server() -> AsyncIterator[str]:
    # CI can run the same wire tests against the built Docker image.
    external_url = os.getenv("ARR_ASSISTANT_TEST_HTTP_URL")
    if external_url:
        yield external_url.rstrip("/")
        return
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "ARR_MCP_TRANSPORT": "http",
        "ARR_MCP_HOST": "127.0.0.1",
        "ARR_MCP_PORT": str(port),
        "ARR_MCP_TOKEN": TOKEN,
        "ARR_MCP_ALLOWED_HOSTS": "media.example.com",
        "RADARR_API_KEY": "",
        "SONARR_API_KEY": "",
        "FASTMCP_CHECK_FOR_UPDATES": "off",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "arr_assistant_mcp.main",
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient() as client:
            async with asyncio.timeout(15):
                while True:
                    if process.returncode is not None:
                        pytest.fail(f"HTTP server exited during startup: {process.returncode}")
                    try:
                        response = await client.get(f"{url}/healthz")
                        if response.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(0.05)
        yield url
    finally:
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()


@pytest.mark.asyncio
async def test_http_authentication_and_request_guards(http_server: str) -> None:
    async with httpx.AsyncClient(base_url=http_server) as client:
        health = await client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        for method in ("POST", "DELETE"):
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                response = await client.request(method, "/mcp", headers=headers, json={})
                assert response.status_code == 401
                assert "bearer" in response.headers["www-authenticate"].lower()
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = await client.post(
            "/mcp", headers={**headers, "Host": "attacker.invalid"}, json={}
        )
        assert response.status_code == 421
        response = await client.post(
            "/mcp", headers={**headers, "Origin": "https://attacker.invalid"}, json={}
        )
        assert response.status_code == 403
        response = await client.get("/healthz", headers={"Host": "media.example.com"})
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_concurrent_http_clients_discover_and_call_tools(http_server: str) -> None:
    async def use_client() -> None:
        async with Client(f"{http_server}/mcp", auth=TOKEN, timeout=10) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} == {
                "test_config",
                "search_movies",
                "add_movie_by_id",
                "search_and_add_show",
                "add_show_by_tvdb_id",
                "get_server_status",
            }
            result = await client.call_tool("test_config", {})
            assert result.is_error is False
            assert result.data["config_loaded"] is True
            assert result.data["radarr_connectivity"] == "no_api_key"
            assert result.data["sonarr_connectivity"] == "no_api_key"

    await asyncio.gather(use_client(), use_client(), use_client())
