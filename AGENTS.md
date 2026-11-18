# AGENTS.md

Python MCP stdio server for Gemini chat, images, and file/URL analysis.
Use uv. The package uses the xob0t Gemini-API fork, not upstream 2.x.

- Install with `uv sync`. Run with `uv run gemini-webapi-mcp`.
- Run `uv run --with pytest pytest` for the mocked Chrome cookie-domain
  regression test. No lint, typecheck, or format command is configured.
- Keep stdout reserved for MCP protocol messages and log to stderr. Never
  log session cookie values or use real credentials for routine checks.
- In `src/gemini_webapi_mcp/server.py`, keep exact `.google.com` filtering:
  the browser cookie library matches domains by substring.
- Preserve image request serialization around shared patch state and the
  native-resolution fallback when the 2× download fails. The image-only
  sister repo uses a different upstream request and download path.
