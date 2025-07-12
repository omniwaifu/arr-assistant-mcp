# Natural Language Media Server MCP

## Project Overview
An MCP server that enables natural language querying and automatic addition of movies/TV shows to self-hosted Radarr and Sonarr instances.

## Core Concept
- User provides natural language description: "I want that Guy Ritchie movie with Daniel Craig from the 2000s"
- LLM processes description and identifies potential matches
- System searches metadata APIs (TMDb/TVDB) for confirmation
- Automatically adds media to Radarr/Sonarr via their REST APIs

## API Structure Differences

### Radarr (Movies)
- **Metadata Source**: The Movie Database (TMDb)
- **URL Structure**: `http://192.168.1.11:7878/movie/{tmdb_id}`
- **API Endpoint**: `/api/v3/movie`
- **Identifier**: TMDb ID (e.g., 4836 for Layer Cake)
- **Advantages**: TMDb has comprehensive movie metadata and flexible search

### Sonarr (TV Shows)
- **Metadata Source**: The TV Database (TVDB) - REQUIRED
- **API Endpoint**: `/api/v3/series`
- **Identifier**: TVDB ID (mandatory - cannot use TMDb or IMDb IDs)
- **Limitations**: Must exist on TVDB; no fallback to other databases
- **Note**: Community requests exist for TMDb support but not implemented as of 2024

## MCP Server Tools

### Core Tools
1. `search_and_add_movie` - Natural language movie search and Radarr addition
2. `search_and_add_show` - Natural language TV show search and Sonarr addition
3. `list_wanted_media` - Show pending downloads in both services
4. `search_existing_media` - Query already downloaded content
5. `get_server_status` - Check Radarr/Sonarr connectivity and health

### Workflow Example
```
User Input: "I want that sci-fi show about time travel with the British guy"
↓
LLM Analysis: Identifies potential matches (Doctor Who, Quantum Leap, etc.)
↓
TMDb/TVDB Search: Find exact series with metadata
↓
User Confirmation: Present options if multiple matches
↓
Sonarr API Call: POST to /api/v3/series with TVDB ID
```

## Technical Architecture

### Configuration
- Radarr URL and API key
- Sonarr URL and API key
- Quality profiles and root folders for each service
- LLM provider settings for natural language processing

### API Integration Points
- **Radarr**: `/api/v3/movie` (POST), `/api/v3/movie/{id}` (GET)
- **Sonarr**: `/api/v3/series` (POST), `/api/v3/series/{id}` (GET)
- **TMDb**: Search and metadata endpoints
- **TVDB**: Search and metadata endpoints (required for Sonarr)

### Error Handling
- Handle metadata source mismatches (TMDb vs TVDB)
- Graceful fallbacks for ambiguous queries
- Connection/authentication error management
- Duplicate detection (don't re-add existing media)

## Implementation Considerations

### Challenges
1. **Metadata Source Split**: Movies use TMDb, TV shows require TVDB
2. **Ambiguous Queries**: Multiple potential matches for vague descriptions
3. **Quality/Format Selection**: Choosing appropriate quality profiles
4. **Authentication**: Secure API key management

### Future Enhancements
- Integration with other *arr services (Prowlarr, Lidarr)
- Watchlist import from streaming platforms
- Intelligent quality profile selection based on content type
- Batch operations for multiple requests

## Development Priority
1. Core movie functionality (Radarr + TMDb integration)
2. TV show functionality (Sonarr + TVDB integration)
3. Enhanced natural language processing
4. Configuration management and error handling
5. Advanced features and integrations