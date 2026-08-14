# MCP Tools Reference

## gemini_chat

Text prompt to Gemini. Supports multi-turn and thinking mode.

**Parameters:**
| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `prompt` | yes | — | Text prompt |
| `model` | no | `gemini-3.6-flash` | Model to use |
| `session_id` | no | — | Session ID for multi-turn |
| `temporary` | no | `False` | Don't save conversation to Gemini history |

```
gemini_chat(prompt="Explain quantum computing")
```

Temporary chat (not saved to history):
```
gemini_chat(prompt="Quick question about cats", temporary=True)
```

Multi-turn:
```
gemini_chat(prompt="Now simpler", session_id="abc123")
```

Thinking mode (shows reasoning):
```
gemini_chat(prompt="Solve step by step: ...", model="gemini-3.1-pro")
```

## gemini_start_chat

Start multi-turn session. Returns `session_id` for use in `gemini_chat`.

**Parameters:**
| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `model` | no | `gemini-3.6-flash` | Model for session |

```
gemini_start_chat()
gemini_start_chat(model="gemini-3.1-pro")
```

## gemini_generate_image

Generate new images or edit existing ones.

**Parameters:**
| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `prompt` | yes | — | Image description or editing instruction |
| `files` | no | — | List of file paths for image editing |
| `model` | no | `gemini-3.6-flash` | Model to use (image generation uses its own model ID) |
| `conversation_id` | no | — | `[cid, rid, rcid]` from previous call for iterative refinement |
| `temporary` | no | `False` | Don't save generation to Gemini history |

**Generate:**
```
gemini_generate_image(prompt="a serene mountain lake at sunset, oil painting style")
```

**Edit existing image:**
```
gemini_generate_image(prompt="make the sky purple", files=["/path/to/image.png"])
```

**Iterative refinement** (continue from previous generation):
```
gemini_generate_image(prompt="make it more dramatic", conversation_id=["c_xxx", "r_xxx", "rc_xxx"])
```

**Output:** PNG saved to `~/Pictures/gemini/`, 2x upscaled resolution. Returns `conversation_id` for continuation.

**Resolution (2x upscale):**
- 16:9: 2816x1536 (native 1408x768, auto-upscaled 2x)
- 9:16: 1536x2816 (native 768x1408, auto-upscaled 2x)
- 1:1: 2048x2048 (native 1024x1024, auto-upscaled 2x)
- Fallback to native if 2x unavailable

**Aspect ratio:** Include in prompt naturally: "wide landscape 16:9", "tall portrait 9:16". Do NOT specify model explicitly — the server picks the best image model automatically.

## gemini_upload_file

Upload file and ask Gemini about it. Supports video, images, PDF, documents.

**Parameters:**
| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `file_path` | yes | — | Absolute path to file |
| `prompt` | no | `"Describe this file."` | Question or instruction |
| `model` | no | `gemini-3.6-flash` | Model to use |
| `temporary` | no | `False` | Don't save conversation to Gemini history |

```
gemini_upload_file(file_path="/path/to/image.png", prompt="What is in this image?")
```

> For **image editing**, use `gemini_generate_image` with the `files` parameter instead.

## gemini_analyze_url

Analyze URL — YouTube videos, webpages, articles.

**Parameters:**
| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `url` | yes | — | URL to analyze |
| `prompt` | no | `"Summarize this content."` | Question about the content |
| `model` | no | `gemini-3.6-flash` | Model to use |
| `temporary` | no | `False` | Don't save conversation to Gemini history |

```
gemini_analyze_url(url="https://youtube.com/watch?v=...", prompt="Summarize this video")
```

## gemini_reset

Re-initialize client when cookies expire. No parameters.

```
gemini_reset()
```

**When to use:** Auth errors, 401/403 responses, "cookie expired" messages.

## Models

| Model | Best for | Notes |
|-------|----------|-------|
| `gemini-3.6-flash` | Text chat, analysis | Fast, default for chat |
| `gemini-3.5-flash-lite` | Lightweight/fast tasks | Cheapest, fastest |
| `gemini-3.1-pro` | Complex reasoning, thinking | Slower, higher quality text |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Auth error / cookies expired | `gemini_reset` |
| Image generation blocked / fails | Call `gemini_reset` first — often fixes transient Google blocks |
| Stream interrupted / timeout | Server auto-retries (watchdog 45s); file editing may need 2-3 retries |
| No images in response | Prompt may violate content policy, rephrase. For file editing: update server (`git pull && uv sync`) |
| Square image despite aspect ratio | Include aspect ratio in prompt text (e.g. "16:9", "9:16", "1:1", "4:3", "3:4") |
| Error 1052 / image generation fails | Google rotated model IDs. Update server to latest version: `git pull && uv sync` |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_PSID` | — | Override `__Secure-1PSID` cookie (instead of reading from Chrome) |
| `GEMINI_PSIDTS` | — | Override `__Secure-1PSIDTS` cookie |
| `GEMINI_ACCOUNT_INDEX` | `0` | Google account index (for multi-account Chrome profiles) |
| `GEMINI_LANGUAGE` | `en` | Language for Gemini responses |

**Cookie auth on headless/remote servers:**

By default, cookies are read automatically from a local Chrome browser via `browser-cookie3`. On headless servers (no Chrome), set `GEMINI_PSID` and `GEMINI_PSIDTS` manually:

1. Open Chrome on any machine → go to `gemini.google.com` → sign in
2. DevTools (F12) → Application → Cookies → `https://gemini.google.com`
3. Copy values of `__Secure-1PSID` and `__Secure-1PSIDTS`
4. Set as environment variables for the MCP server
