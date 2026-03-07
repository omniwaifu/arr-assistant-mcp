# arr-assistant-mcp

MCP server for searching movies and TV shows and adding them to Radarr and Sonarr.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/) for local development.

```bash
git clone <repo>
cd arr-assistant-mcp
uv sync
```

## Run From Source

Add this to your `claude_desktop_config.json` to run the checked-out project directly:

```json
{
  "mcpServers": {
    "arr-assistant": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/path/to/arr-assistant-mcp",
        "src/arr_assistant_mcp/main.py"
      ],
      "env": {
        "RADARR_URL": "http://your-ip:7878",
        "RADARR_API_KEY": "your-radarr-api-key",
        "SONARR_URL": "http://your-ip:8989",
        "SONARR_API_KEY": "your-sonarr-api-key",
        "QUALITY_PROFILE_ID": "1",
        "RADARR_ROOT_FOLDER": "/storage/movies",
        "SONARR_ROOT_FOLDER": "/storage/shows"
      }
    }
  }
}
```

Trailing slashes in `RADARR_URL` and `SONARR_URL` are normalized automatically.

## Build An MCP Bundle

Packaged release artifacts should now use the `.mcpb` extension.

```bash
npm install -g @anthropic-ai/mcpb
mcpb validate .
mcpb pack . arr-assistant-mcp.mcpb
```

Open the resulting `.mcpb` file in Claude Desktop to install it.

## Configuration Notes

- **Radarr/Sonarr API keys**: Settings -> General -> API Key
- **Quality profile**: Use the numeric profile ID from your Radarr or Sonarr instance
- **Root folders**: If omitted, the server auto-detects the first available root folder from each service
- **TVDB API key**: Not required for the current implementation

## Tools

- `test_config()` - Test configuration and connectivity for both Radarr and Sonarr
- `search_movies(title)` - Search for movies by title
- `add_movie_by_id(tmdb_id, root_folder=None)` - Add a movie to Radarr
- `search_and_add_show(description, auto_add=False)` - Search for TV shows and optionally auto-add the only match to Sonarr
- `add_show_by_tvdb_id(tvdb_id, title, root_folder=None)` - Add a show to Sonarr
- `get_server_status()` - Check Radarr and Sonarr status

## Usage

```python
search_movies("The Matrix")
add_movie_by_id(603)

# Specify a custom root folder
add_show_by_tvdb_id(123456, "Attack on Titan", "/storage/anime")
```

Root folders are auto-detected from your Radarr and Sonarr configurations when not provided, but can still be overridden per request.
