"""Arr Assistant MCP server for Radarr and Sonarr."""

import logging
from dataclasses import dataclass
from datetime import datetime
import os
from typing import Any

import httpx
from fastmcp import FastMCP
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_RADARR_URL = "http://localhost:7878"
DEFAULT_SONARR_URL = "http://localhost:8989"
DEFAULT_QUALITY_PROFILE_ID = 1

# Configuration models
@dataclass
class ServerConfig:
    radarr_url: str
    radarr_api_key: str
    sonarr_url: str
    sonarr_api_key: str
    quality_profile_id: int = 1
    radarr_root_folder: str | None = None
    sonarr_root_folder: str | None = None

    def __post_init__(self) -> None:
        self.radarr_url = self.radarr_url.rstrip("/")
        self.sonarr_url = self.sonarr_url.rstrip("/")

# Response models
class MediaSearchResult(BaseModel):
    title: str
    year: int | None = None
    overview: str
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    poster_path: str | None = None
    media_type: str  # "movie" or "tv"

class AddMediaResponse(BaseModel):
    success: bool
    message: str
    media_id: int | None = None

# Initialize FastMCP server
mcp = FastMCP("Arr Assistant MCP Server")

# Global config (will be set via environment or config file)
config: ServerConfig | None = None

class MediaServerAPI:
    """API client for Radarr and Sonarr"""

    def __init__(self, config: ServerConfig, client: httpx.AsyncClient | None = None):
        self.config = config
        self.client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None

    async def __aenter__(self) -> "MediaServerAPI":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def get_radarr_root_folders(self) -> list[dict[str, Any]]:
        """Get available root folders from Radarr"""
        url = f"{self.config.radarr_url}/api/v3/rootfolder"
        headers = {"X-Api-Key": self.config.radarr_api_key}

        try:
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get Radarr root folders: {e}")
            return []

    async def get_sonarr_root_folders(self) -> list[dict[str, Any]]:
        """Get available root folders from Sonarr"""
        url = f"{self.config.sonarr_url}/api/v3/rootfolder"
        headers = {"X-Api-Key": self.config.sonarr_api_key}

        try:
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get Sonarr root folders: {e}")
            return []

    async def search_radarr_movies(self, query: str) -> list[dict[str, Any]]:
        """Search for movies using Radarr's built-in lookup (uses their TMDb access)"""
        url = f"{self.config.radarr_url}/api/v3/movie/lookup"
        headers = {"X-Api-Key": self.config.radarr_api_key}
        params = {"term": query}

        logger.info(f"Radarr lookup request: {url} with term='{query}'")

        try:
            response = await self.client.get(url, params=params, headers=headers)
            logger.info(f"Radarr response status: {response.status_code}")

            if response.status_code == 401:
                logger.error("Radarr authentication failed - check your API key")
                raise Exception("Radarr authentication failed - verify your API key is correct")
            elif response.status_code == 404:
                logger.error("Radarr lookup endpoint not found")
                raise Exception("Radarr lookup endpoint not found")

            response.raise_for_status()
            results = response.json()
            logger.info(f"Radarr returned {len(results)} results for query '{query}'")

            if results:
                logger.info(f"First result: {results[0].get('title')} ({results[0].get('year', 'No year')})")

            return results
        except Exception as e:
            logger.error(f"Radarr lookup error for query '{query}': {e}")
            raise

    async def add_movie_to_radarr(
        self,
        tmdb_id: int,
        title: str,
        root_folder: str | None = None,
    ) -> AddMediaResponse:
        """Add movie to Radarr"""
        url = f"{self.config.radarr_url}/api/v3/movie"
        headers = {"X-Api-Key": self.config.radarr_api_key}

        # Use provided title - Radarr will fetch additional details
        if not title:
            title = f"Movie (TMDb ID: {tmdb_id})"

        payload = {
            "title": title,
            "tmdbId": tmdb_id,
            "qualityProfileId": self.config.quality_profile_id,
            "monitored": True,
            "minimumAvailability": "announced",
            "addOptions": {
                "searchForMovie": True
            }
        }

        # Set root folder (parameter > config > auto-detect)
        if root_folder:
            payload["rootFolderPath"] = root_folder
            logger.info(f"Using specified root folder: {root_folder}")
        elif self.config.radarr_root_folder:
            payload["rootFolderPath"] = self.config.radarr_root_folder
            logger.info(f"Using configured root folder: {self.config.radarr_root_folder}")
        else:
            # Auto-detect first available root folder
            root_folders = await self.get_radarr_root_folders()
            if root_folders:
                payload["rootFolderPath"] = root_folders[0]["path"]
                logger.info(f"Using auto-detected Radarr root folder: {root_folders[0]['path']}")
            else:
                logger.warning("No Radarr root folders found - movie may fail to add")

        try:
            response = await self.client.post(url, json=payload, headers=headers)
            if response.status_code == 201:
                result = response.json()
                return AddMediaResponse(
                    success=True,
                    message=f"Successfully added '{title}' to Radarr",
                    media_id=result.get("id")
                )
            else:
                return AddMediaResponse(
                    success=False,
                    message=f"Failed to add movie: {response.text}"
                )
        except Exception as e:
            logger.error(f"Radarr API error: {e}")
            return AddMediaResponse(
                success=False,
                message=f"Error communicating with Radarr: {str(e)}"
            )

    async def search_sonarr_shows(self, query: str) -> list[dict[str, Any]]:
        """Search for TV shows using Sonarr's built-in lookup"""
        url = f"{self.config.sonarr_url}/api/v3/series/lookup"
        headers = {"X-Api-Key": self.config.sonarr_api_key}
        params = {"term": query}

        logger.info(f"Sonarr lookup request: {url} with term='{query}'")

        try:
            response = await self.client.get(url, params=params, headers=headers)
            logger.info(f"Sonarr response status: {response.status_code}")

            if response.status_code == 401:
                logger.error("Sonarr authentication failed - check your API key")
                raise Exception("Sonarr authentication failed - verify your API key is correct")
            elif response.status_code == 404:
                logger.error("Sonarr lookup endpoint not found")
                raise Exception("Sonarr lookup endpoint not found")

            response.raise_for_status()
            results = response.json()
            logger.info(f"Sonarr returned {len(results)} results for query '{query}'")

            if results:
                logger.info(f"First result: {results[0].get('title')} ({results[0].get('year', 'No year')})")

            return results
        except Exception as e:
            logger.error(f"Sonarr lookup error for query '{query}': {e}")
            raise

    async def add_series_to_sonarr(
        self,
        tvdb_id: int,
        title: str,
        root_folder: str | None = None,
    ) -> AddMediaResponse:
        """Add TV series to Sonarr using TVDB ID"""
        url = f"{self.config.sonarr_url}/api/v3/series"
        headers = {"X-Api-Key": self.config.sonarr_api_key}

        payload = {
            "title": title,
            "tvdbId": tvdb_id,
            "qualityProfileId": self.config.quality_profile_id,
            "monitored": True,
            "seasonFolder": True,
            "addOptions": {
                "searchForMissingEpisodes": True
            }
        }

        # Set root folder (parameter > config > auto-detect)
        if root_folder:
            payload["rootFolderPath"] = root_folder
            logger.info(f"Using specified root folder: {root_folder}")
        elif self.config.sonarr_root_folder:
            payload["rootFolderPath"] = self.config.sonarr_root_folder
            logger.info(f"Using configured root folder: {self.config.sonarr_root_folder}")
        else:
            # Auto-detect first available root folder
            root_folders = await self.get_sonarr_root_folders()
            if root_folders:
                payload["rootFolderPath"] = root_folders[0]["path"]
                logger.info(f"Using auto-detected Sonarr root folder: {root_folders[0]['path']}")
            else:
                logger.warning("No Sonarr root folders found - series may fail to add")

        try:
            response = await self.client.post(url, json=payload, headers=headers)
            if response.status_code == 201:
                result = response.json()
                return AddMediaResponse(
                    success=True,
                    message=f"Successfully added '{title}' to Sonarr",
                    media_id=result.get("id")
                )
            else:
                return AddMediaResponse(
                    success=False,
                    message=f"Failed to add series: {response.text}"
                )
        except Exception as e:
            logger.error(f"Sonarr API error: {e}")
            return AddMediaResponse(
                success=False,
                message=f"Error communicating with Sonarr: {str(e)}"
            )

    async def check_radarr_status(self) -> dict[str, Any]:
        """Check Radarr server status"""
        url = f"{self.config.radarr_url}/api/v3/system/status"
        headers = {"X-Api-Key": self.config.radarr_api_key}

        try:
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()
            return {"status": "connected", "data": response.json()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def check_sonarr_status(self) -> dict[str, Any]:
        """Check Sonarr server status"""
        url = f"{self.config.sonarr_url}/api/v3/system/status"
        headers = {"X-Api-Key": self.config.sonarr_api_key}

        try:
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()
            return {"status": "connected", "data": response.json()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

# MCP Tools
@mcp.tool
async def search_movies(title: str) -> dict[str, Any]:
    """
    Search for movies by title using Radarr's built-in lookup.
    
    Args:
        title: Movie title only (e.g., "The Matrix" or "Primer")
    
    Returns:
        Dict with search results
    """
    logger.info(f"Searching for movies: '{title}'")
    
    if not config:
        error_msg = "Server not configured. Please set up Radarr API key."
        logger.error(error_msg)
        return {"error": error_msg, "results": []}
    
    if not config.radarr_api_key:
        error_msg = "Radarr API key not configured"
        logger.error(error_msg)
        return {"error": error_msg, "results": []}
    
    try:
        async with MediaServerAPI(config) as api:
            logger.info(f"Searching Radarr for: {title}")
            radarr_results = await api.search_radarr_movies(title)
            logger.info(f"Radarr returned {len(radarr_results)} results")

            if not radarr_results:
                return {
                    "message": f"No movies found matching '{title}'",
                    "results": [],
                    "searched_query": title
                }

            results = []
            for movie in radarr_results[:10]:  # Show more results since we're not auto-adding
                result = MediaSearchResult(
                    title=movie.get("title") or "Unknown",
                    year=movie.get("year"),
                    overview=movie.get("overview") or "No overview available",
                    tmdb_id=movie.get("tmdbId"),
                    poster_path=movie.get("remotePoster"),
                    media_type="movie"
                )
                results.append(result)

        return {
            "results": [r.model_dump() for r in results],
            "total_found": len(results),
            "searched_query": title
        }
    except Exception as e:
        error_msg = f"Error during movie search: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"error": error_msg, "results": []}

@mcp.tool
async def add_movie_by_id(tmdb_id: int, root_folder: str | None = None) -> AddMediaResponse:
    """
    Add a specific movie to Radarr using its TMDb ID.
    
    Args:
        tmdb_id: The Movie Database ID for the movie
        root_folder: Optional root folder path (e.g., "/storage/movies")
    
    Returns:
        Result of the add operation
    """
    if not config:
        raise ValueError("Server not configured. Please set up Radarr API key.")
    
    # Use TMDb ID as title placeholder - Radarr will fetch the real title
    title = f"Movie (TMDb ID: {tmdb_id})"

    async with MediaServerAPI(config) as api:
        return await api.add_movie_to_radarr(tmdb_id, title, root_folder)

@mcp.tool
async def search_and_add_show(
    description: str,
    auto_add: bool = False
) -> list[MediaSearchResult]:
    """
    Search for TV shows using natural language description and optionally add to Sonarr.
    
    Args:
        description: Natural language description of the TV show (e.g., "British time travel show with the Doctor")
        auto_add: If True and only one result found, automatically add to Sonarr
    
    Returns:
        List of matching TV shows with metadata
    """
    if not config:
        raise ValueError("Server not configured. Please set up Sonarr API key.")
    
    async with MediaServerAPI(config) as api:
        # Search for TV shows using Sonarr lookup
        tv_results = await api.search_sonarr_shows(description)

        results = []
        for show in tv_results[:5]:  # Limit to top 5 results
            result = MediaSearchResult(
                title=show.get("title") or "Unknown",
                year=show.get("year"),
                overview=show.get("overview") or "No overview available",
                tmdb_id=show.get("tmdbId"),
                tvdb_id=show.get("tvdbId"),
                poster_path=show.get("remotePoster"),
                media_type="tv"
            )
            results.append(result)

        # Auto-add if requested and only one result
        if auto_add and len(results) == 1:
            show = results[0]
            if show.tvdb_id:
                add_result = await api.add_series_to_sonarr(show.tvdb_id, show.title)
                logger.info("Auto-add result for '%s': %s", show.title, add_result.model_dump())
            else:
                logger.warning(f"Cannot auto-add '{show.title}' - no TVDB ID available")

        return results

@mcp.tool
async def add_show_by_tvdb_id(tvdb_id: int, title: str, root_folder: str | None = None) -> AddMediaResponse:
    """
    Add a specific TV show to Sonarr using its TVDB ID.
    
    Args:
        tvdb_id: The TV Database ID for the show
        title: The title of the show
        root_folder: Optional root folder path (e.g., "/storage/anime")
    
    Returns:
        Result of the add operation
    """
    if not config:
        raise ValueError("Server not configured. Please set up Sonarr API key.")
    
    async with MediaServerAPI(config) as api:
        return await api.add_series_to_sonarr(tvdb_id, title, root_folder)

@mcp.tool
async def test_config() -> dict[str, Any]:
    """
    Test the current configuration and API connectivity.
    
    Returns:
        Configuration status and basic connectivity tests
    """
    logger.info("Testing configuration...")
    
    if not config:
        return {"error": "No configuration loaded"}
    
    status = {
        "config_loaded": True,
        "radarr_url": config.radarr_url,
        "sonarr_url": config.sonarr_url,
        "radarr_api_key_set": bool(config.radarr_api_key),
        "sonarr_api_key_set": bool(config.sonarr_api_key),
        "quality_profile_id": config.quality_profile_id,
        "radarr_root_folder": config.radarr_root_folder,
        "sonarr_root_folder": config.sonarr_root_folder
    }
    
    async with MediaServerAPI(config) as api:
        if config.radarr_api_key:
            radarr_status = await api.check_radarr_status()
            status["radarr_connectivity"] = radarr_status["status"]
            if radarr_status["status"] == "connected":
                status["radarr_version"] = radarr_status["data"].get("version")
            else:
                status["radarr_error"] = radarr_status["message"]
        else:
            status["radarr_connectivity"] = "no_api_key"

        if config.sonarr_api_key:
            sonarr_status = await api.check_sonarr_status()
            status["sonarr_connectivity"] = sonarr_status["status"]
            if sonarr_status["status"] == "connected":
                status["sonarr_version"] = sonarr_status["data"].get("version")
            else:
                status["sonarr_error"] = sonarr_status["message"]
        else:
            status["sonarr_connectivity"] = "no_api_key"

    return status

@mcp.tool
async def get_server_status() -> dict[str, Any]:
    """
    Check the status and connectivity of Radarr and Sonarr servers.
    
    Returns:
        Status information for both servers
    """
    if not config:
        return {"error": "Server not configured"}
    
    async with MediaServerAPI(config) as api:
        radarr_status = await api.check_radarr_status()
        sonarr_status = await api.check_sonarr_status()

    return {
        "radarr": radarr_status,
        "sonarr": sonarr_status,
        "timestamp": datetime.now().isoformat()
    }

def setup_config(
    radarr_url: str,
    radarr_api_key: str,
    sonarr_url: str,
    sonarr_api_key: str,
    quality_profile_id: int = 1,
    radarr_root_folder: str | None = None,
    sonarr_root_folder: str | None = None,
) -> None:
    """Setup server configuration"""
    global config
    config = ServerConfig(
        radarr_url=radarr_url,
        radarr_api_key=radarr_api_key,
        sonarr_url=sonarr_url,
        sonarr_api_key=sonarr_api_key,
        quality_profile_id=quality_profile_id,
        radarr_root_folder=radarr_root_folder,
        sonarr_root_folder=sonarr_root_folder
    )


def _get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default

    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid %s value %r; falling back to %s", name, value, default)
        return default


def load_config_from_env() -> None:
    """Load server configuration from environment variables."""
    setup_config(
        radarr_url=os.getenv("RADARR_URL", DEFAULT_RADARR_URL),
        radarr_api_key=os.getenv("RADARR_API_KEY", ""),
        sonarr_url=os.getenv("SONARR_URL", DEFAULT_SONARR_URL),
        sonarr_api_key=os.getenv("SONARR_API_KEY", ""),
        quality_profile_id=_get_int_env("QUALITY_PROFILE_ID", DEFAULT_QUALITY_PROFILE_ID),
        radarr_root_folder=os.getenv("RADARR_ROOT_FOLDER"),
        sonarr_root_folder=os.getenv("SONARR_ROOT_FOLDER"),
    )

if __name__ == "__main__":
    load_config_from_env()
    mcp.run()
