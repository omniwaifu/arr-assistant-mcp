# arr-assistant-mcp

MCP server for adding movies and TV shows to Radarr/Sonarr via natural language queries.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo>
cd arr-assistant-mcp
uv sync
```

## Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "arr-assistant": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/arr-assistant-mcp/",
        "run",
        "src/arr_assistant_mcp/main.py"
      ],
      "env": {
        "RADARR_URL": "http://your-ip:7878",
        "RADARR_API_KEY": "your-radarr-api-key",
        "SONARR_URL": "http://your-ip:8989",
        "SONARR_API_KEY": "your-sonarr-api-key"
      }
    }
  }
}
```

## API Keys

- **Radarr/Sonarr**: Settings → General → API Key

## Tools

- `test_config()` - Test configuration and connectivity
- `search_movies(title)` - Search for movies by title
- `add_movie_by_id(tmdb_id, root_folder=None)` - Add movie to Radarr
- `search_and_add_show(description)` - Search and add TV shows to Sonarr
- `add_show_by_tvdb_id(tvdb_id, title, root_folder=None)` - Add show to Sonarr
- `get_server_status()` - Check Radarr/Sonarr status

## Usage

```
search_movies("The Matrix")
add_movie_by_id(603)

# Specify custom root folder
add_show_by_tvdb_id(123456, "Attack on Titan", "/storage/anime")
```

Root folders are auto-detected from your Radarr/Sonarr configurations, but can be overridden per-request.