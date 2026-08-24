"""MCP Server for Google Gemini via browser cookies."""

import logging
import warnings

# Quiet-by-default startup: MCP stdio clients surface every stderr line in
# their own logs, so third-party chatter stays off unless explicitly enabled.
warnings.filterwarnings("ignore", message=".*incomplete definition.*")
logging.getLogger("mcp").setLevel(logging.WARNING)

from gemini_webapi_mcp.server import mcp  # noqa: E402


def main():
    """Entry point for the gemini-webapi-mcp command."""
    try:
        mcp.run()
    except KeyboardInterrupt:
        pass  # clean Ctrl+C exit: the stdio transport otherwise unwinds loudly
