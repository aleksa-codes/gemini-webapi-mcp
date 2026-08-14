<h1 align="center">gemini-webapi-mcp</h1>

<p align="center">
  MCP server for Google Gemini — image generation/editing, chat and file analysis via browser cookies.<br>
  No API keys. Free.
</p>

<p align="center">
  <a href="https://github.com/AndyShaman/gemini-webapi-mcp/blob/main/LICENSE"><img src="https://img.shields.io/github/license/AndyShaman/gemini-webapi-mcp?style=flat-square&color=green" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/MCP-compatible-8A2BE2?style=flat-square" alt="MCP">
  <a href="https://github.com/AndyShaman/gemini-webapi-mcp/stargazers"><img src="https://img.shields.io/github/stars/AndyShaman/gemini-webapi-mcp?style=flat-square&color=yellow" alt="Stars"></a>
</p>

<p align="center">
  <a href="https://t.me/AI_Handler"><img src="https://img.shields.io/badge/Telegram-Author's_Channel-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram"></a>
  &nbsp;
  <a href="https://www.youtube.com/channel/UCLkP6wuW_P2hnagdaZMBtCw"><img src="https://img.shields.io/badge/YouTube-Author's_Channel-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="YouTube"></a>
</p>

---

## Features

- **Image generation** from text descriptions (Nano Banana 2 with aspect ratio support)
- **2x resolution** — automatically downloads upscaled version (2048x2048 → 2816x1536 and above)
- **Image editing** — send an image + prompt to get a modified version
- **File analysis** — video, images, PDF, documents
- **Text chat** with Gemini (Flash, Pro, Flash-Thinking)
- **Auto-authentication** via Chrome browser cookies

## Quick Start

### 1. Log into Gemini

Open Chrome, go to [gemini.google.com](https://gemini.google.com) and sign in.

### 2. Install the MCP server

**From GitHub (no clone needed):**

```bash
uv run --with "gemini-webapi-mcp @ git+https://github.com/AndyShaman/gemini-webapi-mcp.git" gemini-webapi-mcp
```

**Local install:**

```bash
git clone https://github.com/AndyShaman/gemini-webapi-mcp.git
cd gemini-webapi-mcp
uv sync
uv run gemini-webapi-mcp
```

### 3. Add MCP config

<details>
<summary><b>Claude Code</b></summary>

```bash
claude mcp add-json gemini '{"command":"uv","args":["run","--with","gemini-webapi-mcp @ git+https://github.com/AndyShaman/gemini-webapi-mcp.git","gemini-webapi-mcp"]}'
```

Or add manually to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "gemini": {
      "command": "uv",
      "args": ["run", "--with", "gemini-webapi-mcp @ git+https://github.com/AndyShaman/gemini-webapi-mcp.git", "gemini-webapi-mcp"]
    }
  }
}
```

</details>

<details>
<summary><b>Claude Desktop</b></summary>

Add to Claude Desktop config:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "gemini": {
      "command": "uv",
      "args": ["run", "--with", "gemini-webapi-mcp @ git+https://github.com/AndyShaman/gemini-webapi-mcp.git", "gemini-webapi-mcp"]
    }
  }
}
```

</details>

<details>
<summary><b>Other MCP clients</b></summary>

Use the standard MCP stdio config:

```json
{
  "mcpServers": {
    "gemini": {
      "command": "uv",
      "args": ["run", "--with", "gemini-webapi-mcp @ git+https://github.com/AndyShaman/gemini-webapi-mcp.git", "gemini-webapi-mcp"]
    }
  }
}
```

Config file path depends on your MCP client.

</details>
**Local install (after cloning)** — replace args with:

```json
"args": ["--directory", "/path/to/gemini-webapi-mcp", "run", "gemini-webapi-mcp"]
```

### 4. Install the skill for Claude Code (optional)

The [`skill/`](skill/) folder contains a Claude Code skill — prompting tips, tool documentation and an image generation guide. The skill auto-activates when working with Gemini.

```bash
cp -r skill ~/.claude/skills/gemini-mcp
```

### 5. Verify

Run the server manually — if it initializes without errors, everything works:

```bash
uv run --with "gemini-webapi-mcp @ git+https://github.com/AndyShaman/gemini-webapi-mcp.git" gemini-webapi-mcp
```

Then open Claude Code or Claude Desktop and try: *"Generate a watercolor cat image with Gemini"*.

## Authentication

The server reads cookies from Chrome automatically via `browser-cookie3`.

> **Multiple Google accounts?** Set `GEMINI_ACCOUNT_INDEX` — the account number from Chrome (0 = first, 1 = second, ...). Check the order by clicking your avatar on gemini.google.com.

If cookie auto-detection fails, set them manually:

1. Open Chrome DevTools on gemini.google.com → Application → Cookies
2. Copy `__Secure-1PSID` and `__Secure-1PSIDTS` values
3. Add to your MCP config:

```json
{
  "mcpServers": {
    "gemini": {
      "command": "uv",
      "args": ["run", "--with", "gemini-webapi-mcp @ git+https://github.com/AndyShaman/gemini-webapi-mcp.git", "gemini-webapi-mcp"],
      "env": {
        "GEMINI_PSID": "your__Secure-1PSID_value",
        "GEMINI_PSIDTS": "your__Secure-1PSIDTS_value"
      }
    }
  }
}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GEMINI_PSID` | Cookie value `__Secure-1PSID` | auto from Chrome |
| `GEMINI_PSIDTS` | Cookie value `__Secure-1PSIDTS` | auto from Chrome |
| `GEMINI_LANGUAGE` | Gemini response language (`ru`, `en`, `ja`, ...) | `en` |
| `GEMINI_ACCOUNT_INDEX` | Google account index (0, 1, 2, ...) | `0` |

## High Resolution (2x)

The server automatically requests an upscaled version of each generated image — the same mechanism used by the "Download" button in Gemini's web interface. Google performs server-side upscaling, delivering images at 2x resolution:

| Model | Native | 2x (downloaded) |
|-------|--------|-----------------|
| Flash-Thinking (16:9) | 1408x768 | 2816x1536 |
| Flash-Thinking (9:16) | 768x1376 | 1536x2752 |
| Flash-Thinking (1:1) | 1024x1024 | 2048x2048 |

If the 2x version is unavailable (timeout, network error), the server automatically falls back to native resolution.

## Tools

| Tool | Description |
|------|-------------|
| `gemini_generate_image` | Generate new or edit existing images |
| `gemini_upload_file` | Analyze files — video, images, PDF, documents |
| `gemini_analyze_url` | Analyze URLs — YouTube videos, webpages, articles |
| `gemini_chat` | Text chat (single or multi-turn) |
| `gemini_start_chat` | Start a multi-turn session |
| `gemini_reset` | Re-initialize client on auth errors |

## Models

| Model | Default for | Notes |
|-------|-------------|-------|
| `gemini-3.6-flash` | chat, file analysis | Fast |
| `gemini-3.5-flash-lite` | — | Lightweight, fastest |
| `gemini-3.1-pro` | — | Complex reasoning |

## Usage Examples

Once configured, Claude calls the right tools automatically. Just ask in chat:

| Task | What to tell Claude |
|------|---------------------|
| Generate an image | *"Generate a watercolor cat with Gemini"* |
| Edit an image | *"Edit /path/to/cat.png with Gemini — make the cat gray"* |
| Iterative refinement | *"Now make the background darker"* (same conversation) |
| Analyze a video | *"Analyze this video with Gemini: https://youtube.com/watch?v=..."* |
| Analyze a file | *"Upload /path/to/doc.pdf to Gemini and summarize it"* |

Tools that Claude will call:

```
gemini_generate_image(prompt="a cat in watercolor style")
gemini_generate_image(prompt="make it gray", files=["/path/to/cat.png"])
gemini_generate_image(prompt="make the background darker", conversation_id=["c_abc", "r_123", "rc_456"])
gemini_chat(prompt="Quick question about cats", temporary=True)
gemini_analyze_url(url="https://youtube.com/watch?v=...", prompt="Summarize this video")
gemini_upload_file(file_path="/path/to/doc.pdf", prompt="Summarize key points")
```

## Acknowledgements

This project is built on top of [gemini-webapi](https://github.com/HanaokaYuzu/Gemini-API) by [@HanaokaYuzu](https://github.com/HanaokaYuzu) (fork by [@xob0t](https://github.com/xob0t/Gemini-API) with curl_cffi support) — a reverse-engineered async Python wrapper for the Google Gemini web app. Licensed under AGPL-3.0.

## License

[AGPL-3.0](LICENSE) — free to use, modify, and distribute, provided the source code remains open.

**[@AndyShaman](https://github.com/AndyShaman)** · [gemini-webapi-mcp](https://github.com/AndyShaman/gemini-webapi-mcp)