---
name: gemini-mcp
description: Use when user asks you to create/edit images or to analyze an image (when you do not support vision capabilities natively). Always use `gemini_reset` for the first request and use temporary=True to avoid saving to history.
---

# Gemini MCP Skill

Interact with Google Gemini via `gemini-webapi-mcp` MCP server.

## Reference Router

| Task | Read |
|------|------|
| Tool parameters, models, troubleshooting | [tools.md](references/tools.md) |
| Image generation prompting | [image-prompting.md](references/image-prompting.md) |

## Quick Start

**Chat:**
```
gemini_chat(prompt="Explain quantum computing")
```

**Generate image:**
```
gemini_generate_image(prompt="A cinematic wide shot of a futuristic city at sunset, volumetric fog, neon reflections on wet streets")
```

**Edit image:**
```
gemini_generate_image(prompt="Change the background to a sunset beach. Keep everything else exactly the same.", files=["/path/to/image.png"])
```

**Analyze file:**
```
gemini_upload_file(file_path="/path/to/doc.pdf", prompt="Summarize key points")
```

**Analyze URL/YouTube:**
```
gemini_analyze_url(url="https://youtube.com/watch?v=...", prompt="Summarize this video")
```

## Key Facts

- Call `gemini_reset` before the first request in a session; use `temporary=True` to skip saving to Gemini history
- Images saved to `~/Pictures/gemini/` as PNG, 2x upscaled resolution
- Always include aspect ratio at the end of the prompt (e.g. "16:9", "9:16", "1:1", "4:3", "3:4")
- Do NOT specify model for image generation — server picks the best one automatically
- Do NOT re-verify generated images by sending them back through `gemini_upload_file`. Trust the generation response (returned paths + text). Only analyze an image when the user explicitly asks you to look at it.
- If image generation fails or gets blocked, call `gemini_reset` first — it re-initializes the client and often fixes transient Google blocks
- Auth errors: call `gemini_reset` to refresh cookies
- Models and full parameter reference: see [tools.md](references/tools.md)
