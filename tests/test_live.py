from __future__ import annotations

import os
from collections.abc import Generator

import pytest

from arr_assistant_mcp import main as server_main
from arr_assistant_mcp.main import MediaServerAPI


@pytest.fixture
def live_config() -> Generator[None, None, None]:
    if os.getenv("ARR_ASSISTANT_LIVE_TESTS") != "1":
        pytest.skip("set ARR_ASSISTANT_LIVE_TESTS=1 to run read-only live tests")

    required = ("RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.fail(f"missing live-test environment variables: {', '.join(missing)}")

    previous = server_main.config
    server_main.load_config_from_env()
    yield
    server_main.config = previous


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_connectivity_and_root_folder_reads(live_config: None) -> None:
    status = await server_main.test_config()

    assert status["radarr_connectivity"] == "connected"
    assert status["sonarr_connectivity"] == "connected"
    assert status["radarr_version"]
    assert status["sonarr_version"]
    assert server_main.config is not None

    async with MediaServerAPI(server_main.config) as api:
        radarr_root_folders = await api.get_radarr_root_folders()
        sonarr_root_folders = await api.get_sonarr_root_folders()

    assert MediaServerAPI._get_first_valid_root_folder(radarr_root_folders)
    assert MediaServerAPI._get_first_valid_root_folder(sonarr_root_folders)
