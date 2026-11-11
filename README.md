# Arr Assistant MCP

MCP server for searching movies and TV shows and adding them to Radarr and Sonarr.

Run locally over stdio, or alongside your Arr services as an authenticated HTTP server in Docker.
The same six tools are available through either transport.

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
        "--locked",
        "--no-dev",
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

## Docker / Remote MCP Server

Run this on your media server or VPS; desktop clients connect to its Streamable HTTP endpoint
at `/mcp`. Arr API keys stay on the server. HTTP mode requires a separate shared bearer token,
including on a private network. Anyone holding that token can use all tools, including adds.
This is a single-household/deployment server, not an isolated multi-user hosting service.

```bash
cp .env.example .env
openssl rand -hex 32
# Edit .env: paste the generated value into ARR_MCP_TOKEN and configure the Arr URLs/API keys.
docker compose up -d --build
docker compose ps
```

The image runs as a non-root user with locked runtime dependencies. Compose uses a read-only
filesystem and publishes `127.0.0.1:8000` by default. No media mounts or persistent volumes are
needed. `/healthz` is an unauthenticated process-liveness check; it does not contact Arr or
return configuration. Inspect startup failures with `docker compose logs arr-assistant`.

### Networking

- **SSH tunnel:** Leave the default loopback binding. On your desktop run
  `ssh -N -L 8000:127.0.0.1:8000 user@media-server`, then connect to
  `http://127.0.0.1:8000/mcp` with the bearer token.
- **Direct LAN/VPN:** Set `ARR_MCP_BIND_ADDRESS` to your server's LAN/VPN IP and add that IP
  or hostname to `ARR_MCP_ALLOWED_HOSTS`. For example, `192.168.1.50` for both settings makes
  the endpoint `http://192.168.1.50:8000/mcp`. Plain HTTP exposes the token to that network;
  use HTTPS or an SSH tunnel where the network is not trusted.
- **VPS / HTTPS:** Put a TLS reverse proxy in front of the loopback-published port and add
  the public hostname (e.g. `mcp.example.com`) to `ARR_MCP_ALLOWED_HOSTS`. Preserve the
  `Host` and `Authorization` headers and forward `/mcp` without rewriting its path. Keep the
  backend port private. Clients connect to `https://mcp.example.com/mcp`.
- **Alongside Arr in Compose:** Add the `arr-assistant` service to your existing Compose
  project, or attach it to the same Docker network. Use `RADARR_URL=http://radarr:7878` and
  `SONARR_URL=http://sonarr:8989`, substituting your service names. With a separate Compose
  project, use reachable server addresses or explicitly join the existing external network.

Inside the container, `localhost` refers to the assistant container, not your host or the Arr
containers. Root folders such as `/movies` are paths **as seen by Radarr/Sonarr**. You do not
need to mount those paths into this container.

### Connect Desktop Clients

Clients need Streamable HTTP support and the ability to supply
`Authorization: Bearer <ARR_MCP_TOKEN>`. Use the same token configured on the server, and
replace the URL in these examples with your LAN, tunnel, or HTTPS address.

For [Codex](https://developers.openai.com/codex/mcp), add this to `~/.codex/config.toml`:

```toml
[mcp_servers.arr-assistant]
url = "http://127.0.0.1:8000/mcp"
bearer_token_env_var = "ARR_MCP_TOKEN"
```

Make `ARR_MCP_TOKEN` available in the environment of the desktop/CLI process before starting
Codex. It is the client token, not a Radarr or Sonarr API key.

For [Claude Code](https://code.claude.com/docs/en/mcp), merge this into `.mcp.json`:

```json
{
  "mcpServers": {
    "arr-assistant": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer ${ARR_MCP_TOKEN}"
      }
    }
  }
}
```

Set `ARR_MCP_TOKEN` in Claude Code's environment before launching it. Other clients can use
the same URL/header pair. This server uses a pre-shared token, not an OAuth browser login;
clients that require OAuth or only support stdio need a compatible bridge, or can keep using
the local source/MCPB installation below. Cloud-hosted connectors also need a reachable endpoint;
they cannot connect directly to your desktop's SSH tunnel or a private LAN address.

### HTTP From Source

```bash
ARR_MCP_TRANSPORT=http ARR_MCP_TOKEN="your-generated-token-at-least-32-characters" \
  uv run --locked --no-dev python -m arr_assistant_mcp.main
```

Also supply your Arr environment variables. Source runs do not automatically load `.env`;
Compose reads it for interpolation. Keep local `.env` files private and out of Git.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARR_MCP_TRANSPORT` | `stdio` (`http` in image) | Select stdio or Streamable HTTP |
| `ARR_MCP_HOST` | `127.0.0.1` (`0.0.0.0` in image) | HTTP listen address |
| `ARR_MCP_PORT` | `8000` | Source listen port / Compose published port |
| `ARR_MCP_TOKEN` | None; required for HTTP | Random bearer token, at least 32 characters |
| `ARR_MCP_ALLOWED_HOSTS` | Loopback hosts | Extra accepted Host header names/IPs, comma-separated |
| `ARR_MCP_BIND_ADDRESS` | `127.0.0.1` | Compose host-side published address |

Allowed hosts omit schemes, paths, and ports. Host validation and browser Origin validation
are enabled. A `421` response usually means the client-facing hostname/IP needs to be added
to `ARR_MCP_ALLOWED_HOSTS`; `401` means the bearer token is missing or incorrect. HTTP requests
are stateless, so independent desktop clients can connect concurrently without sharing MCP
session state. They all operate on the same configured Arr libraries. Rotate the shared token
by changing it on the server, recreating the container, and updating clients.

## Build An MCP Bundle

Packaged release artifacts should now use the `.mcpb` extension.

```bash
npm ci --prefix .github/mcpb-tooling --ignore-scripts
npm audit --prefix .github/mcpb-tooling --audit-level=moderate
npm test --prefix .github/mcpb-tooling
npm exec --prefix .github/mcpb-tooling -- mcpb validate manifest.json
npm exec --prefix .github/mcpb-tooling -- mcpb pack . arr-assistant-mcp.mcpb
```

Open the resulting `.mcpb` file in Claude Desktop to install it.

The tooling pins Zod 4.6.6 to address
[GHSA-mrhx-c7xc-m3w5](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5), since MCPB 2.1.2
still requests Zod 3. The tooling tests check our manifest's validation behavior with this
override. Revisit the override when MCPB updates its dependency.

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
uv run pip-audit --local
bash scripts/test-container.sh
```

CI also runs weekly and can be triggered manually, so dependency advisories are checked even
when there are no code changes. Runtime examples use `--locked --no-dev` to install the checked-in
dependency versions without development tools.

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
matching the project version (for example, `v0.2.3`) runs linting, tests, a dependency
audit, and package validation before publishing the MCPB, wheel, and source distribution to a
GitHub release.
