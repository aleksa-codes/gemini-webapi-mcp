# Gemini WebAPI MCP

Generate and edit images, chat with Gemini, or analyze files and URLs from an
MCP client. The server uses your signed-in Gemini web session, not the official
API. If you only need images, use the
[image-only server](https://github.com/aleksa-codes/gemini-webapi-image-mcp).

## Connect

Install [uv](https://docs.astral.sh/uv/) and sign in at
[gemini.google.com](https://gemini.google.com) in Chrome on the machine running
the MCP process. The package declares Python 3.10 or later.

For OpenCode, omit `--global` to register only for the current project:

```sh
opencode mcp add gemini --global -- uvx --from git+https://github.com/aleksa-codes/gemini-webapi-mcp.git gemini-webapi-mcp
```

For Claude Code or Claude Desktop, add the same stdio server to the client's
MCP configuration:

```json
{
  "mcpServers": {
    "gemini": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/aleksa-codes/gemini-webapi-mcp.git",
        "gemini-webapi-mcp"
      ]
    }
  }
}
```

For a local checkout, use `uv --directory /absolute/path/to/gemini-webapi-mcp run gemini-webapi-mcp`.
Once connected, try asking the client to generate a watercolor cat or summarize
a public YouTube video.

## Tools

| Tool                                | What it does                                                                                     |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ |
| `gemini_generate_image`             | Generate an image, edit files passed in `files`, or refine a result using its `conversation_id`. |
| `gemini_chat` / `gemini_start_chat` | Ask a question or start a multi-turn session.                                                    |
| `gemini_upload_file`                | Analyze a local image, video, PDF, or document.                                                  |
| `gemini_analyze_url`                | Analyze a web page or YouTube URL.                                                               |
| `gemini_reset`                      | Reinitialize the client and read authentication again.                                           |

Images save to `~/Pictures/gemini/` by default. Use `output_dir` per call or
`GEMINI_OUTPUT_DIR` for the server. The server requests 2× downloads and falls
back to native resolution if unavailable. Pass `temporary: true` on supported
calls if you do not want the request saved in Gemini history.
See the [tool reference](skill/references/tools.md) for parameters and models.

## Authentication and settings

Leave cookie overrides unset when Chrome authentication works. Set
`GEMINI_ACCOUNT_INDEX` for multiple signed-in accounts (default `0`) or
`CHROME_COOKIE_FILE` for a custom Chrome cookie file.

If the MCP process cannot access Chrome, supply your own Gemini session values
through private environment settings as `GEMINI_PSID` (`__Secure-1PSID`) and,
preferably, `GEMINI_PSIDTS` (`__Secure-1PSIDTS`). Never commit or share them.
If sign-in fails, refresh the session and call `gemini_reset`. Error 1096 can
also be account-side; it does not always mean the cookies are invalid.

| Setting                   | Default                        |
| ------------------------- | ------------------------------ |
| `GEMINI_LANGUAGE`         | `en`                           |
| `GEMINI_GEN_TIMEOUT`      | 600 seconds                    |
| `GEMINI_DOWNLOAD_TIMEOUT` | 60 seconds                     |
| `GEMINI_SKIP_2X`          | `0`; set `1` to skip upscaling |

Advanced diagnostics: `GEMINI_DEBUG_TIMING=1` logs timings,
`GEMINI_NO_REMAP=1` disables model header remapping, and
`GEMINI_IMAGE_MODEL_ID` overrides the internal image model ID.

## For agents

See [AGENTS.md](AGENTS.md) for contributor checks. To use the server,
install the optional [Gemini MCP skill](skill/SKILL.md) by copying the whole
`skill/` directory into your client's skills directory as `gemini-mcp`
(for example, `~/.claude/skills/gemini-mcp` in Claude Code).

## Credits

Forked from [AndyShaman/gemini-webapi-mcp](https://github.com/AndyShaman/gemini-webapi-mcp).
Uses [HanaokaYuzu's Gemini-API](https://github.com/HanaokaYuzu/Gemini-API)
via the [xob0t fork](https://github.com/xob0t/Gemini-API).

## License

[AGPL-3.0-or-later](LICENSE)
