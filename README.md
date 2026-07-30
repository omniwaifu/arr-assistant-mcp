# Arr Assistant MCP

MCP server for searching movies and TV shows and adding them to Radarr and Sonarr.

The server talks directly to the Radarr and Sonarr v3 APIs. Searches and status checks are
read-only; the `add_*` tools and `search_and_add_show(..., auto_add=True)` create media entries
and start searches in the configured Arr service.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/) for local development.

```bash
git clone https://github.com/omniwaifu/arr-assistant-mcp.git
cd arr-assistant-mcp
uv sync --group dev
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
        "RADARR_URL": "https://radarr.example.com",
        "RADARR_API_KEY": "your-radarr-api-key",
        "SONARR_URL": "https://sonarr.example.com",
        "SONARR_API_KEY": "your-sonarr-api-key",
        "QUALITY_PROFILE_ID": "1",
        "RADARR_ROOT_FOLDER": "/storage/movies",
        "SONARR_ROOT_FOLDER": "/storage/shows"
      }
    }
  }
}
```

Trailing slashes in `RADARR_URL` and `SONARR_URL` are normalized automatically. API keys are
required for the corresponding service. Never commit them; pass them through your MCP client or
local environment. Prefer HTTPS because Arr API keys are sent with every request. Plain HTTP is
safe for loopback URLs; for a trusted LAN or VPN where HTTPS is unavailable, the server allows
plain HTTP but logs a warning identifying the service and destination.

## Build An MCP Bundle

Packaged release artifacts should now use the `.mcpb` extension.

```bash
npm ci --prefix .github/mcpb-tooling --ignore-scripts
npm audit --prefix .github/mcpb-tooling --audit-level=moderate
npm exec --prefix .github/mcpb-tooling -- mcpb validate manifest.json
npm exec --prefix .github/mcpb-tooling -- mcpb pack . arr-assistant-mcp.mcpb
```

Open the resulting `.mcpb` file in Claude Desktop to install it.

## Configuration Notes

- **Radarr/Sonarr API keys**: Settings > General > Security > API Key
- **Quality profile**: Use the numeric profile ID from your Radarr or Sonarr instance
- **Root folders**: If omitted, the server auto-detects the first available root folder from each service

## Tools

- `test_config()` - Test configuration and connectivity for both Radarr and Sonarr
- `search_movies(title)` - Search for movies by title
- `add_movie_by_id(tmdb_id, root_folder=None)` - Add a movie to Radarr
- `search_and_add_show(description, auto_add=False)` - Search for TV shows and optionally auto-add the only match to Sonarr; returns both the matches and an explicit `auto_add_result`
- `add_show_by_tvdb_id(tvdb_id, title, root_folder=None)` - Add a show to Sonarr
- `get_server_status()` - Check Radarr and Sonarr status

## Usage

```python
search_movies("The Matrix")
add_movie_by_id(603)

# A search is read-only unless auto_add is explicitly enabled.
search_and_add_show("Doctor Who", auto_add=False)

# Specify a custom root folder
add_show_by_tvdb_id(123456, "Attack on Titan", "/storage/anime")
```

Root folders are auto-detected from your Radarr and Sonarr configurations when not provided, but can still be overridden per request.

## Development and Testing

Run the local checks with:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest
```

The default suite never contacts a real Arr instance. An additional opt-in suite performs only
read-only status and root-folder requests against locally configured services:

```bash
ARR_ASSISTANT_LIVE_TESTS=1 \
RADARR_URL=https://radarr.example.com \
RADARR_API_KEY=your-radarr-api-key \
SONARR_URL=https://sonarr.example.com \
SONARR_API_KEY=your-sonarr-api-key \
uv run pytest tests/test_live.py -v
```

Use environment variables or a local ignored `.env` file for credentials. Do not paste real API
keys into source files, test fixtures, shell scripts, or commits.

## Releases

Versions are kept in sync across `pyproject.toml`, `manifest.json`, and the package. Pushing a tag
matching the project version (for example, `v0.2.1`) runs linting, tests, a dependency
audit, and package validation before publishing the MCPB, wheel, and source distribution to a
GitHub release.
