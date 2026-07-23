# AGENTS.md

## What is this

MCP server for Google Gemini — image generation/editing, chat, and file analysis via browser cookies (no API keys). Single Python package, no monorepo.

## Setup

```bash
uv sync                # install deps (requires Python 3.10+)
uv run gemini-webapi-mcp   # run the MCP server
```

## Commands

| Task | Command |
|------|---------|
| Install deps | `uv sync` |
| Run server | `uv run gemini-webapi-mcp` |
| Run watermark tests | `pytest tests/test_watermark.py` |

There is no linter, typechecker, or formatter configured. No CI/CD workflows exist.

## Architecture

All source lives in `src/gemini_webapi_mcp/`. The entire app is essentially one file:

- `__init__.py` — entry point, calls `mcp.run()`
- `server.py` — MCP tool definitions, GeminiClient patching, watermark removal, cookie resolution

**Entry flow:** `gemini-webapi-mcp` CLI → `__init__.py:main()` → `FastMCP.run()` (stdio transport).

**Key internals:**
- `_patch_client()` monkey-patches `GeminiClient` to inject browser-compatible request headers/body params for fast image generation, and intercepts response parsing to capture image download tokens.
- `_fetch_download_url()` calls Google's `c8o8Fe` RPC to get 2x upscaled download URLs.
- `_remove_watermark()` does deterministic reverse-alpha-blending using calibrated star-shape maps in `assets/*.npy`.

## Critical conventions

- **stdout = MCP protocol only.** All logging goes to stderr. Never print to stdout.
- **Image generation is serialized.** `_image_lock` (asyncio.Lock) ensures one concurrent image generation call. `_image_mode` global toggles request patching on/off per call.
- **Image generation has a hard timeout** (default 600s, `GEMINI_GEN_TIMEOUT`). Gemini responses are erratic (22s–345s).
- **Images save to `~/Pictures/gemini/`.** The directory is created automatically.

## Environment variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `GEMINI_PSID` / `GEMINI_PSIDTS` | Manual cookie override | auto from Chrome |
| `GEMINI_ACCOUNT_INDEX` | Google account index (0, 1, ...) | `0` |
| `GEMINI_LANGUAGE` | Response language (`en`, `ru`, `ja`, ...) | `en` |
| `GEMINI_WM_KEEP` | Set `1` to skip watermark removal | `0` |
| `GEMINI_GEN_TIMEOUT` | Image generation timeout (seconds) | `600` |
| `GEMINI_DOWNLOAD_TIMEOUT` | Image download timeout (seconds) | `60` |
| `GEMINI_SKIP_2X` | Set `1` to skip 2x upscale RPC | `0` |
| `GEMINI_NO_REMAP` | Set `1` to skip model-ID remap in headers | `0` |
| `GEMINI_DEBUG_TIMING` | Set `1` to log per-stage wall-time | `0` |
| `GEMINI_IMAGE_MODEL_ID` | Override model ID for image gen requests | `56fdd199312815e2` |

## Testing

Tests are in `tests/test_watermark.py`. They are standalone (can run with `python` or `pytest`), use synthetic + one real fixture image, and test the watermark removal pipeline in isolation (no Gemini auth needed).

```bash
pytest tests/test_watermark.py -v
```

## Dependencies

Key: `gemini-webapi` (from GitHub, not PyPI), `mcp`, `browser-cookie3`, `orjson`, `Pillow`, `numpy`, `curl-cffi`.

The `gemini-webapi` dependency is a git reference (`xob0t/Gemini-API`). It uses `curl_cffi` for TLS fingerprint impersonation. `browser-cookie3` handles Chrome cookie extraction.

## License

AGPL-3.0. Code from `gemini-webapi` (also AGPL-3.0) is used via git dependency.
