"""
MCP Server for Google Gemini via browser cookies.

Uses gemini_webapi library to access Gemini Web App for free,
without requiring paid API keys. Authentication is done through
browser cookies (__Secure-1PSID and __Secure-1PSIDTS).
"""

import asyncio
import json
import logging
import os
import random
import re
import string
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP, Context

# ---------------------------------------------------------------------------
# Logging (stderr only — stdout reserved for MCP stdio transport)
# ---------------------------------------------------------------------------
logger = logging.getLogger("gemini_mcp")
logger.addHandler(logging.StreamHandler(sys.stderr))
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
IMAGES_DIR = Path.home() / "Pictures" / "gemini"
DEFAULT_MODEL = "gemini-3.0-flash"

# Hard ceiling for a single image-generation call (seconds). The StreamGenerate
# response via gemini_webapi is erratically slow (measured 22s..345s for the
# same prompt) while the same account generates in ~10s in the browser — the
# library's stall-watchdog + @running(retry=5) backoff can otherwise stretch a
# call to minutes. We cap the whole call so it either returns or fails fast with
# a clear message instead of hanging the MCP client. This is an upper bound;
# fast generations still return as soon as Gemini responds.
#
# 600s is sized for the worst case: image-edit on a portrait reference with a
# dense layout (text/logos/details). Such edits routinely stall 3–4× × 45s
# inside Nano Banana 2 before yielding the result (~210s wall-time observed).
# Override with GEMINI_GEN_TIMEOUT.
GEN_TIMEOUT = float(os.environ.get("GEMINI_GEN_TIMEOUT", "600"))
# Per-network-op timeout for image download in image.save() (seconds). Without
# this the CDN fetch of the full-size (=s0, ~4.5MB) image can hang forever.
DOWNLOAD_TIMEOUT = float(os.environ.get("GEMINI_DOWNLOAD_TIMEOUT", "60"))

# Optional stage timing: set GEMINI_DEBUG_TIMING=1 to log per-stage wall-time.
_DEBUG_TIMING = os.environ.get("GEMINI_DEBUG_TIMING") == "1"
# c8o8Fe 2x-upscale RPC gives full-resolution downloads (~1792×2390 for portrait
# vs ~896×1200 preview). Costs ~20s/image extra; disable with GEMINI_SKIP_2X=1.
_SKIP_2X = os.environ.get("GEMINI_SKIP_2X", "0") != "0"
# Skip the model-id remap + version bump in patched_request (which forces the
# slow thinking-advanced model). Set to "1" to send the requested model as-is.
_NO_REMAP = os.environ.get("GEMINI_NO_REMAP") == "1"


def _stage(label: str, t0: float) -> float:
    """Log elapsed seconds since t0 for a named stage when timing is enabled."""
    import time
    now = time.monotonic()
    if _DEBUG_TIMING:
        logger.info("[timing] %s: %.2fs", label, now - t0)
    return now

# ---------------------------------------------------------------------------
# Watermark removal — deterministic reverse alpha-blend.
#
# Gemini stamps a 48px "✦" sparkle whose position AND opacity are a property of
# the generation PIPELINE, not of the current request:
#   • txt2img pipeline → 48px logo, 32px margin, alpha≈0.50  (mode "txt")
#   • edit  pipeline   → 48px logo, 96px margin, alpha≈0.30  (mode "edit")
# Both share the identical logo shape (alpha-map correlation 0.9999); only the
# opacity differs (edit ≈ 60% of txt2img — its watermark is downscaled from a 2x
# canvas). Removal reverses the alpha-blend in place — no NCC search:
#     original = (watermarked - premult) / (1 - alpha)
# The alpha/premult maps in assets/ were calibrated from real outputs and recover
# the true blend params, so removal is background-independent (clean on charcoal
# AND on white).
#
# A CONTINUATION (conversation_id, no file this turn) INHERITS the pipeline of
# the conversation ROOT: a conversation born from a file-upload stays in the edit
# pipeline → margin 96 for ALL its continuations. The server process is
# short-lived (one per `mcp-cli call`), so it cannot remember the root from
# memory — we persist cid→mode in a small JSON (see _record_conv_mode). When the
# cid is known we pick the position deterministically (works even on a busy
# corner, since reverse-alpha is content-independent). For a FOREIGN cid (born
# before this fix / in the browser) we fall back to detection across the two
# candidate spots, with a self-check that reverts if it would stamp a ghost.
# This replaces gwt-mini, which only knew the margin-32 anchor and over-subtracted
# the edit watermark (leaving a dark ✦ ghost).
# Honours GEMINI_WM_KEEP=1 as a diagnostics kill-switch.
# ---------------------------------------------------------------------------
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_BASE_LOGO = 48                       # logo size at preview resolution
_WM_MARGIN = {"edit": 96, "txt": 32}  # mode -> margin from bottom-right corner
_wm_maps: dict = {}                   # cache: "edit"/"txt" -> (alpha, premult)
_wm_shape = None                      # cache: normalized ✦ shape (0..1) for detection
_CONV_MODES_PATH = IMAGES_DIR / ".wm_conv_modes.json"
_CONV_MODES_LOCK = IMAGES_DIR / ".wm_conv_modes.lock"


def _load_wm_map(key: str):
    """Load the calibrated (alpha, premult) maps for the "edit"/"txt" watermark."""
    import numpy as np
    if key not in _wm_maps:
        alpha = np.load(_ASSETS_DIR / f"wm_alpha_{key}.npy").astype(np.float32)
        premult = np.load(_ASSETS_DIR / f"wm_premult_{key}.npy").astype(np.float32)
        _wm_maps[key] = (alpha, premult)
    return _wm_maps[key]


def _load_wm_shape():
    """Normalized ✦ shape (0..1), shared by both modes — used for detection."""
    global _wm_shape
    if _wm_shape is None:
        alpha, _ = _load_wm_map("edit")
        _wm_shape = alpha / float(alpha.max())
    return _wm_shape


def _resize_map(m, logo):
    """Bilinear-resize a 48px alpha/premult map to `logo` px (for 2x upscale)."""
    import numpy as np
    from PIL import Image
    if m.shape[0] == logo:
        return m
    if m.ndim == 2:
        return np.asarray(Image.fromarray(m).resize((logo, logo), Image.BILINEAR),
                          np.float32)
    return np.stack([np.asarray(Image.fromarray(m[..., c]).resize(
        (logo, logo), Image.BILINEAR), np.float32) for c in range(m.shape[2])], -1)


def _plane_bg(g, shape):
    """Least-squares background plane fit over pixels outside the ✦ (shape≈0)."""
    import numpy as np
    m = shape < 0.06
    ys, xs = np.mgrid[0:g.shape[0], 0:g.shape[1]]
    A = np.c_[xs[m], ys[m], np.ones(int(m.sum()))]
    coef, *_ = np.linalg.lstsq(A, g[m], rcond=None)
    return coef[0] * xs + coef[1] * ys + coef[2]


def _star_corr(box, shape):
    """Correlation of background-subtracted luminance with the ✦ shape.

    ~+1 = bright sparkle present, ~0 = clean background, strongly negative = a
    dark ghost (e.g. over-subtraction). Background-robust via a plane fit.
    """
    import numpy as np
    g = box.mean(2)
    d = g - _plane_bg(g, shape)
    core = shape > 0.15
    dv = d[core] - d[core].mean()
    sv = shape[core] - shape[core].mean()
    denom = float(np.sqrt((dv ** 2).sum() * (sv ** 2).sum()))
    return float((dv * sv).sum() / denom) if denom > 1e-9 else 0.0


def _is_neutral(box, shape):
    """True if the ✦ core is neutral grey (Gemini's mark) vs coloured content."""
    core = shape > 0.3
    spread = (box.max(2) - box.min(2))[core]
    return float(spread.mean()) < 28.0


def _reverse_at(arr, x0, y0, logo, alpha, premult):
    """Reverse the alpha-blend in arr[y0:y0+logo, x0:x0+logo] in place."""
    import numpy as np
    box = arr[y0:y0 + logo, x0:x0 + logo]
    inv = np.clip(1.0 - alpha, 1e-3, 1.0)[..., None]
    arr[y0:y0 + logo, x0:x0 + logo] = np.clip((box - premult) / inv, 0, 255)


def _detect_mode(arr, w, h):
    """Detect which spot holds the ✦ for a foreign conversation (mode 'auto').

    Returns "edit" / "txt" if a sparkle is confidently found, else None. Probes
    only the two known anchors (margin 96 vs 32) at preview scale — not a free
    NCC search — and requires a neutral-grey shape match above threshold.
    """
    shape = _load_wm_shape()
    logo = _BASE_LOGO
    best = None
    for mode in ("edit", "txt"):
        margin = _WM_MARGIN[mode]
        if w < logo + margin or h < logo + margin:
            continue
        x0, y0 = w - margin - logo, h - margin - logo
        box = arr[y0:y0 + logo, x0:x0 + logo]
        corr = _star_corr(box, shape)
        if corr > 0.5 and _is_neutral(box, shape):
            if best is None or corr > best[1]:
                best = (mode, corr)
    return best[0] if best else None


def _get_conv_mode(cid: Optional[str]) -> Optional[str]:
    """Look up the persisted pipeline mode ("edit"/"txt") for a conversation."""
    if not cid or not _CONV_MODES_PATH.exists():
        return None
    try:
        entry = json.loads(_CONV_MODES_PATH.read_text()).get(cid)
        return entry.get("mode") if entry else None
    except Exception:
        return None


def _record_conv_mode(cid: Optional[str], mode: Optional[str]) -> None:
    """Persist cid→mode (concurrency-safe: flock + atomic replace, keep last 500)."""
    if not cid or mode not in ("edit", "txt"):
        return
    import fcntl
    import time
    try:
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CONV_MODES_LOCK, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            data = {}
            if _CONV_MODES_PATH.exists():
                try:
                    data = json.loads(_CONV_MODES_PATH.read_text())
                except Exception:
                    data = {}
            data[cid] = {"mode": mode, "ts": time.time()}
            if len(data) > 500:
                data = dict(sorted(data.items(),
                                   key=lambda kv: kv[1].get("ts", 0),
                                   reverse=True)[:500])
            tmp = _CONV_MODES_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, _CONV_MODES_PATH)
    except Exception as exc:
        logger.warning("conv-mode record failed for %s: %s", cid, exc)


def _remove_watermark(image_path: str, mode: str = "txt",
                      upscaled: bool = False) -> Optional[str]:
    """Reverse-alpha-blend the Gemini ✦ out of image_path in place.

    mode: "edit" (margin 96) / "txt" (margin 32) → deterministic; "auto" →
    detect across both anchors (foreign cid) with a ghost self-check. upscaled
    scales the 48px maps for c8o8Fe 2x output. Returns the mode actually applied
    ("edit"/"txt") for caller self-learning, or None if skipped/not found.
    Honours GEMINI_WM_KEEP=1.
    """
    if os.environ.get("GEMINI_WM_KEEP") == "1":
        return None
    try:
        import numpy as np
        from PIL import Image
    except Exception as exc:
        logger.warning("numpy/PIL unavailable — watermark NOT removed: %s", exc)
        return None
    try:
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        arr = np.asarray(img, np.float32)
    except Exception as exc:
        logger.warning("watermark removal failed to open %s: %s", image_path, exc)
        return None

    # Resolve the mode → for "auto", detect from the image (foreign cid path).
    if mode == "auto":
        try:
            mode = _detect_mode(arr, w, h)
        except Exception as exc:
            logger.warning("watermark auto-detect failed on %s: %s", image_path, exc)
            mode = None
        if mode is None:
            logger.info("Watermark not detected (foreign cid) — left as-is: %s",
                        image_path)
            return None
        detected = True
    else:
        detected = False

    try:
        alpha, premult = _load_wm_map(mode)
    except Exception as exc:
        logger.warning("watermark maps missing in %s — NOT removed: %s",
                       _ASSETS_DIR, exc)
        return None

    scale = 2 if upscaled else 1
    logo = _BASE_LOGO * scale
    margin = _WM_MARGIN[mode] * scale
    if w < logo + margin or h < logo + margin:
        return None
    if scale != 1:
        alpha, premult = _resize_map(alpha, logo), _resize_map(premult, logo)

    x0, y0 = w - margin - logo, h - margin - logo
    try:
        _reverse_at(arr, x0, y0, logo, alpha, premult)
        # Detection path: guard against stamping a ghost on a clean corner —
        # if the removal made the spot worse (strong inverse shape), revert.
        if detected and scale == 1:
            shape = _load_wm_shape()
            if _star_corr(arr[y0:y0 + logo, x0:x0 + logo], shape) < -0.3:
                logger.info("Watermark auto-removal reverted (would ghost): %s",
                            image_path)
                return None
        Image.fromarray(arr.astype(np.uint8)).save(image_path)
        logger.info("Watermark removed (%s, margin %d%s) from %s", mode, margin,
                    ", detected" if detected else "", image_path)
        return mode
    except Exception as exc:
        logger.warning("watermark removal failed on %s: %s", image_path, exc)
        return None


# ---------------------------------------------------------------------------
# Cookie resolution: env vars → browser-cookie3 → error
# ---------------------------------------------------------------------------

def _resolve_cookies() -> tuple[str, str]:
    """Resolve Gemini auth cookies with clear priority chain.

    1. Environment variables GEMINI_PSID / GEMINI_PSIDTS (explicit override).
    2. Chrome browser cookies via browser-cookie3 (automatic).
    3. RuntimeError with actionable instructions.

    Returns (psid, psidts). psidts may be empty.
    Cookie values are never logged.
    """
    # --- Priority 1: explicit env vars ---
    psid = os.environ.get("GEMINI_PSID", "")
    psidts = os.environ.get("GEMINI_PSIDTS", "")
    if psid:
        logger.info("Using Gemini cookies from environment variables")
        return psid, psidts

    # --- Priority 2: Chrome browser cookies ---
    try:
        import browser_cookie3

        cookie_file = os.environ.get("CHROME_COOKIE_FILE") or None
        cj = browser_cookie3.chrome(domain_name=".google.com", cookie_file=cookie_file)
        for cookie in cj:
            if cookie.name == "__Secure-1PSID" and cookie.value:
                psid = cookie.value
            elif cookie.name == "__Secure-1PSIDTS" and cookie.value:
                psidts = cookie.value
        if psid:
            logger.info("Using Gemini cookies from Chrome browser")
            return psid, psidts
        logger.warning("browser-cookie3: no __Secure-1PSID cookie found in Chrome")
    except ImportError:
        logger.warning("browser-cookie3 not installed — cannot read cookies from Chrome")
    except Exception as exc:
        logger.warning("browser-cookie3: failed to read Chrome cookies — %s", type(exc).__name__)

    # --- Nothing worked ---
    raise RuntimeError(
        "Gemini cookies not found. Options:\n"
        "  1. Log into gemini.google.com in Chrome and install browser-cookie3, or\n"
        "  2. Set GEMINI_PSID (and optionally GEMINI_PSIDTS) environment variables."
    )


def _make_gen_id() -> str:
    """Generate a client-side gen_id for c8o8Fe RPC (16-char repeating pattern)."""
    base = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return (base * 3)[:16]


# ---------------------------------------------------------------------------
# Lifespan: initialise GeminiClient once, reuse across all tool calls
# ---------------------------------------------------------------------------

@asynccontextmanager
async def app_lifespan(server):
    from gemini_webapi import GeminiClient

    psid, psidts = _resolve_cookies()

    account_index = int(os.environ.get("GEMINI_ACCOUNT_INDEX", "0"))
    client = GeminiClient(secure_1psid=psid, secure_1psidts=psidts or None, account_index=account_index)
    if account_index:
        logger.info("Using Google account index: %d", account_index)
    await client.init(timeout=300, watchdog_timeout=45, auto_close=False, auto_refresh=True)
    _patch_client(client)

    yield {"gemini_client": client, "chat_sessions": {}}

    await client.close()


mcp = FastMCP("gemini-webapi-mcp", lifespan=app_lifespan)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client(ctx: Context):
    return ctx.request_context.lifespan_context["gemini_client"]


def _get_sessions(ctx: Context) -> dict:
    return ctx.request_context.lifespan_context["chat_sessions"]


_image_mode = False
_image_lock = asyncio.Lock()

# Populated by _patched_parse hook during StreamGenerate response parsing.
_image_tokens: dict[str, str] = {}   # preview_url -> download_token
_last_metadata: list = []             # [cid, rid, rcid, ...] from last response


def _patch_client(gemini_client):
    """Patch GeminiClient for image generation and 2x download support.

    1. Override model ID in header (Google rotates IDs periodically).
    2. Add browser-compatible body params and extra headers during image generation.
    3. Intercept response parsing to capture image download tokens for c8o8Fe RPC.
    """
    # Model id used by the browser for fast image generation (Flash, captured
    # 2026-05-21 from a real StreamGenerate request on a logged-in session).
    # The previous map forced "e051ce1aa80aa576" = flash-THINKING-advanced, the
    # slow Nano-Banana-thinking route that streamed `data_analysis_tool` for
    # 20s..345s. The browser uses "56fdd199312815e2" (flash-advanced) which
    # returns in ~10s. Override via GEMINI_IMAGE_MODEL_ID if Google rotates it.
    _IMAGE_MODEL_ID = os.environ.get("GEMINI_IMAGE_MODEL_ID", "56fdd199312815e2")
    # Capability flags array — the browser sends [4,5,6,8] (we used to send [4]).
    _IMAGE_MODEL_CAPS = "[4,5,6,8]"

    # Browser-compatible body params (indices in inner_req_list), captured from a
    # real browser image-generation request (2026-05-21). These route the request
    # to the fast image path; the prior values (6:[0], 17:[[0]], 68:1) matched the
    # slow path.
    _BROWSER_PARAMS = {
        1: [os.environ.get("GEMINI_LANGUAGE", "en")],
        6: [1],
        7: 1,
        10: 1,
        11: 0,
        17: [[1]],
        18: 0,
        27: 1,
        30: [4],
        41: [1],
        53: 0,
        61: [],
        68: 2,
    }

    http = gemini_client.client  # curl_cffi.AsyncSession
    _orig_request = http.request

    async def patched_request(method, url, **kwargs):
        global _image_mode
        if method == "POST" and "StreamGenerate" in str(url) and _image_mode:
            headers = kwargs.get("headers") or {}

            # Per-request UUID — the browser uses an UPPERCASE uuid, embedded in
            # both jspb headers AND inner[59], all three must match.
            req_uuid = str(uuid.uuid4()).upper()

            # Replace the model header with the exact browser shape for fast image
            # generation, rather than string-patching the library's slow header.
            # Browser: [1,null,null,null,"<id>",null,null,0,[4,5,6,8],null,null,2,null,null,1,1,"<UUID>"]
            if not _NO_REMAP:
                headers["x-goog-ext-525001261-jspb"] = (
                    '[1,null,null,null,"' + _IMAGE_MODEL_ID + '",null,null,0,'
                    + _IMAGE_MODEL_CAPS + ',null,null,2,null,null,1,1,"' + req_uuid + '"]'
                )

            headers["x-goog-ext-73010989-jspb"] = "[0]"
            headers["x-goog-ext-73010990-jspb"] = "[0,0,0]"
            headers["x-goog-ext-525005358-jspb"] = json.dumps([req_uuid, 1])

            kwargs["headers"] = headers

            # Inject browser-compatible body params into f.req
            data = kwargs.get("data")
            if isinstance(data, dict) and "f.req" in data:
                try:
                    outer = json.loads(data["f.req"])
                    inner = json.loads(outer[1])
                    # Force the captured browser values (overwrite, not only-if-None:
                    # the library pre-sets some of these to slow-path values).
                    for idx, val in _BROWSER_PARAMS.items():
                        if idx < len(inner):
                            inner[idx] = val
                    # Sync UUID with header
                    inner[59] = req_uuid

                    # Fix file_data format:
                    # Library:  [[[url], "name"]]
                    # Browser:  [[[url, 1, null, "mime"], "name", null*6, [0]]]
                    file_data = inner[0][3] if isinstance(inner[0], list) and len(inner[0]) > 3 else None
                    if file_data and isinstance(file_data, list):
                        _MIME_MAP = {
                            ".png": "image/png", ".jpg": "image/jpeg",
                            ".jpeg": "image/jpeg", ".webp": "image/webp",
                            ".gif": "image/gif", ".bmp": "image/bmp",
                        }
                        for fd in file_data:
                            if isinstance(fd, list) and len(fd) == 2:
                                url_arr, filename = fd[0], fd[1]
                                if isinstance(url_arr, list) and len(url_arr) == 1:
                                    ext = Path(filename).suffix.lower() if isinstance(filename, str) else ""
                                    mime = _MIME_MAP.get(ext, "image/png")
                                    fd[0] = [url_arr[0], 1, None, mime]
                                    fd.extend([None, None, None, None, None, None, [0]])

                    outer[1] = json.dumps(inner)
                    data["f.req"] = json.dumps(outer)
                    kwargs["data"] = data
                    if _DEBUG_TIMING:
                        logger.info("[req] model_hdr=%s", headers.get("x-goog-ext-525001261-jspb"))
                        logger.info("[req] inner idx 6=%s 7=%s 17=%s 30=%s 68=%s len=%d",
                                    inner[6] if len(inner) > 6 else "?",
                                    inner[7] if len(inner) > 7 else "?",
                                    inner[17] if len(inner) > 17 else "?",
                                    inner[30] if len(inner) > 30 else "?",
                                    inner[68] if len(inner) > 68 else "?", len(inner))
                except Exception as _e:
                    if _DEBUG_TIMING:
                        logger.warning("[req] patch failed: %s", _e)

        return await _orig_request(method, url, **kwargs)

    http.request = patched_request

    # --- Patch _parse_generated_images for new dict-based response format ---
    # Google changed response structure: [12][7][0] (list) -> [12][0]["8"] (dict).
    # See HanaokaYuzu/Gemini-API issues #229, #260, #264.
    import gemini_webapi.client as _gwc
    from gemini_webapi.utils import (
        get_nested_value,
        parse_response_by_frame as _orig_parse,
    )
    from gemini_webapi.types import GeneratedImage
    import orjson as _json

    _orig_parse_images = _gwc._parse_generated_images

    def _patched_parse_images(candidate_data, proxy=None, cookies=None, account_index=0, session_kwargs=None):
        # Try original parser first (old list-based format)
        result = _orig_parse_images(candidate_data, proxy, cookies, account_index, session_kwargs)
        if result:
            return result

        # Fallback: new dict-based format at [12][0]["8"]
        val12 = get_nested_value(candidate_data, [12])
        if not isinstance(val12, list) or not val12:
            return result
        entry = val12[0]
        if not isinstance(entry, dict) or "8" not in entry:
            return result
        generated_images = []
        for gen_img_data in entry["8"]:
            # Structure: [[[null, null, null, [null, 1, "filename.png", "url", ...], ...], ...]]
            url_arr = get_nested_value(gen_img_data, [0, 0, 3])
            if isinstance(url_arr, list) and len(url_arr) >= 4:
                url = url_arr[3]
                title = url_arr[2] or "[Generated Image]"
                token = url_arr[4] if len(url_arr) > 4 else None
                if url and isinstance(url, str) and url.startswith("http"):
                    if token:
                        _image_tokens[url] = token
                    # Force a download timeout so image.save()'s CDN fetch of the
                    # full-size (=s0) image can never hang the call forever.
                    sk = dict(session_kwargs or {})
                    sk.setdefault("timeout", DOWNLOAD_TIMEOUT)
                    generated_images.append(
                        GeneratedImage(
                            url=url,
                            title=f"[Generated Image]",
                            alt="",
                            proxy=proxy,
                            cookies=cookies,
                            account_index=account_index,
                            session_kwargs=sk,
                        )
                    )
        if generated_images:
            logger.info("Parsed %d images from new dict-based response format", len(generated_images))
        return generated_images

    _gwc._parse_generated_images = _patched_parse_images

    # --- Wrap parse_response_by_frame to capture image download tokens ---
    def _patched_parse(buffer):
        parts, remaining = _orig_parse(buffer)
        for part in parts:
            inner_json_str = get_nested_value(part, [2])
            if not inner_json_str:
                continue
            try:
                part_json = _json.loads(inner_json_str)
                # Capture conversation metadata (cid/rid)
                m_data = get_nested_value(part_json, [1])
                if isinstance(m_data, list) and len(m_data) >= 2 and m_data[0]:
                    if len(_last_metadata) >= 3:
                        _last_metadata[0] = m_data[0]
                        _last_metadata[1] = m_data[1]
                    else:
                        _last_metadata.clear()
                        _last_metadata.extend(m_data)
                # Capture image download tokens + rcid from candidates
                candidates = get_nested_value(part_json, [4], [])
                for cand in candidates:
                    rcid = get_nested_value(cand, [0])
                    if rcid and isinstance(rcid, str) and rcid.startswith("rc_"):
                        if len(_last_metadata) >= 2:
                            if len(_last_metadata) == 2:
                                _last_metadata.append(rcid)
                            else:
                                _last_metadata[2] = rcid
                    # Old format: [12][7][0]
                    for gid in get_nested_value(cand, [12, 7, 0], []):
                        url = get_nested_value(gid, [0, 3, 3])
                        token = get_nested_value(gid, [0, 3, 5])
                        if url and token:
                            _image_tokens[url] = token
                    # New dict format: [12][0]["8"]
                    val12 = get_nested_value(cand, [12])
                    if isinstance(val12, list) and val12 and isinstance(val12[0], dict):
                        for gid in val12[0].get("8", []):
                            url_arr = get_nested_value(gid, [0, 0, 3])
                            if isinstance(url_arr, list) and len(url_arr) >= 5:
                                url, token = url_arr[3], url_arr[4]
                                if url and token:
                                    _image_tokens[url] = token
            except Exception:
                pass
        return parts, remaining

    _gwc.parse_response_by_frame = _patched_parse
    logger.info("Patched GeminiClient with browser-compatible parameters")


def _handle_error(e: Exception) -> str:
    from gemini_webapi import AuthError, APIError, RequestTimeoutError

    if isinstance(e, AuthError):
        return (
            "Error: Authentication failed. Cookies may have expired. "
            "Re-login to gemini.google.com in Chrome, then call gemini_reset."
        )
    if isinstance(e, RequestTimeoutError):
        return "Error: Request timed out. Try again or use a lighter model."
    if isinstance(e, APIError):
        return f"Error: Gemini API error — {e}"
    return f"Error: {type(e).__name__} — {e}"


async def _fetch_download_url(client, token: str, prompt: str, metadata: list, image_index: int = 0) -> str | None:
    """Call c8o8Fe RPC to get a high-resolution (2x) download URL for a generated image.

    Google stores a 2x upscaled version accessible only through this RPC endpoint.
    Returns the download URL or None on failure.
    """
    import orjson as _json
    from gemini_webapi.constants import Endpoint
    from gemini_webapi.utils import parse_response_by_frame, get_nested_value

    cid = metadata[0] if metadata else None
    rid = metadata[1] if len(metadata) > 1 else None
    rcid = metadata[2] if len(metadata) > 2 else None
    if not (rid and rcid and cid):
        logger.warning("c8o8Fe skipped: missing metadata (cid/rid/rcid)")
        return None

    gen_id = _make_gen_id()
    inner_payload = _json.dumps([
        [
            [None, None, None, [None, None, None, None, None, token]],
            [f"http://googleusercontent.com/image_generation_content/{image_index}", image_index],
            None,
            [19, prompt],
            None, None, None, None, None,
            gen_id,
        ],
        [rid, rcid, cid, None, gen_id],
        1, 0, 1,
    ]).decode("utf-8")

    outer_payload = _json.dumps(
        [[["c8o8Fe", inner_payload, None, "generic"]]]
    ).decode("utf-8")

    params: dict = {
        "rpcids": "c8o8Fe",
        "_reqid": client._reqid,
        "rt": "c",
        "source-path": Endpoint.get_source_path(client.account_index),
    }
    client._reqid += 100000
    if client.build_label:
        params["bl"] = client.build_label
    if client.session_id:
        params["f.sid"] = client.session_id

    try:
        resp = await client.client.post(
            Endpoint.get_batch_exec_url(client.account_index),
            params=params,
            data={"at": client.access_token, "f.req": outer_payload},
            headers={
                "x-goog-ext-525001261-jspb": "[1,null,null,null,null,null,null,0,[4,4]]",
                "x-goog-ext-73010989-jspb": "[0]",
            },
            timeout=60,
        )
        if resp.status_code != 200:
            logger.warning("c8o8Fe returned status %d", resp.status_code)
            return None

        text = resp.text
        if text.startswith(")]}'"):
            text = text[4:].lstrip()
        parts, _ = parse_response_by_frame(text)
        # parse_response_by_frame returns each sublist as a separate part:
        # part = ['wrb.fr', 'c8o8Fe', '["url"]', None, None, None, 'generic']
        for part in parts:
            if isinstance(part, list) and len(part) > 2 and part[1] == "c8o8Fe":
                inner_str = part[2]
                if inner_str and isinstance(inner_str, str):
                    inner = _json.loads(inner_str)
                    if isinstance(inner, list) and inner:
                        return inner[0]
        logger.warning("c8o8Fe: no download URL in response (%d parts parsed)", len(parts))
    except Exception as exc:
        logger.warning("c8o8Fe failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="gemini_start_chat",
    annotations={
        "title": "Start Gemini Chat Session",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def gemini_start_chat(
    ctx: Context,
    model: Optional[str] = None,
) -> str:
    """Start a new multi-turn chat session with Gemini.

    The session maintains conversation history so follow-up messages
    have full context. Pass the returned session_id to gemini_chat.

    Args:
        model: Model name for this session. Defaults to gemini-3.0-flash.

    Returns:
        JSON with session_id to use in subsequent gemini_chat calls.
    """
    try:
        client = _get_client(ctx)
        chat = client.start_chat(model=model or DEFAULT_MODEL)
        session_id = str(uuid.uuid4())[:8]
        _get_sessions(ctx)[session_id] = chat
        return json.dumps({
            "session_id": session_id,
            "model": model or DEFAULT_MODEL,
            "message": f"Chat session started. Use session_id '{session_id}' in gemini_chat.",
        })
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="gemini_chat",
    annotations={
        "title": "Gemini Chat",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def gemini_chat(
    prompt: str,
    ctx: Context,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Send a text prompt to Google Gemini and get a response.

    Args:
        prompt: The text prompt to send to Gemini.
        model: Model name (e.g. 'gemini-3.0-flash', 'gemini-3.0-pro',
               'gemini-3.0-flash-thinking'). Defaults to gemini-3.0-flash.
        session_id: Optional session ID from gemini_start_chat for
                    multi-turn conversation with context.

    Returns:
        Gemini's text response. When using flash-thinking model,
        also includes the model's reasoning process.
    """
    try:
        client = _get_client(ctx)

        if session_id:
            sessions = _get_sessions(ctx)
            chat = sessions.get(session_id)
            if not chat:
                return f"Error: Session '{session_id}' not found. Start a new one with gemini_start_chat."
            response = await chat.send_message(prompt)
        else:
            response = await client.generate_content(
                prompt, model=model or DEFAULT_MODEL
            )

        text = response.text or "(empty response)"
        thoughts = response.thoughts
        if thoughts:
            return f"**Thinking:**\n{thoughts}\n\n**Response:**\n{text}"
        return text
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="gemini_generate_image",
    annotations={
        "title": "Gemini Image Generation",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def gemini_generate_image(
    prompt: str,
    ctx: Context,
    model: Optional[str] = None,
    files: Optional[list[str]] = None,
    conversation_id: Optional[list[str]] = None,
) -> str:
    """Generate or edit images with Gemini.

    Without files: generates a new image from the text prompt.
    With files: edits/transforms the provided image(s) based on the prompt.

    Pass conversation_id from a previous call to continue refining images
    in the same conversation thread (e.g. "make it more dramatic", "add rain").
    You can also use a cid from the Gemini web URL (gemini.google.com/app/{cid}).

    Images are saved to ~/Pictures/gemini/ and full file paths are returned.

    Args:
        prompt: Description of the image to generate, or editing instruction
                (e.g. 'change the background to blue', 'make it a cartoon').
        model: Model name. Defaults to gemini-3.0-flash-thinking
               (Nano Banana 2, supports non-square aspect ratios).
        files: Optional list of file paths to images to edit/transform.
        conversation_id: Optional list of [cid, rid, rcid] from a previous
                         gemini_generate_image response to continue the conversation.
                         Passing just [cid] (from browser URL) also works.

    Returns:
        JSON with generated image paths, conversation_id for continuation, or an error message.
    """
    global _image_mode
    import time
    t0 = time.monotonic()
    try:
        client = _get_client(ctx)

        # Validate input files
        resolved_files = []
        if files:
            for f in files:
                p = Path(f).expanduser().resolve()
                if not p.exists():
                    return f"Error: File not found — {p}"
                resolved_files.append(str(p))

        chat = None
        async with _image_lock:
            t = _stage("acquired image lock", t0)
            _image_mode = True
            try:
                if conversation_id:
                    chat = client.start_chat(
                        metadata=conversation_id,
                        model=model or "gemini-3.0-flash-thinking",
                    )
                    gen_coro = chat.send_message(prompt, files=resolved_files or None)
                else:
                    kwargs = {"model": model or "gemini-3.0-flash-thinking"}
                    if resolved_files:
                        kwargs["files"] = resolved_files
                    gen_coro = client.generate_content(prompt, **kwargs)
                # Hard cap: never let the library's stall-retry loop run for
                # minutes when Gemini throttles the account. Fail fast instead.
                response = await asyncio.wait_for(gen_coro, timeout=GEN_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("generate_content exceeded %.0fs cap — aborting", GEN_TIMEOUT)
                return (
                    f"Error: Gemini did not return an image within {GEN_TIMEOUT:.0f}s "
                    "via the library (the browser is usually faster). Try again."
                )
            finally:
                _image_mode = False
            _stage("generate_content returned", t)

        if not response.images:
            return response.text or "No images were generated. Try rephrasing your prompt."

        # --- Try to get 2x download URLs via c8o8Fe RPC ---
        # Always prefer _last_metadata from monkey-patched response parsing
        # (captures raw stream data needed for c8o8Fe). Fall back to chat metadata.
        if _last_metadata and _last_metadata[0]:
            metadata = list(_last_metadata)
        elif chat:
            metadata = [chat.cid or "", chat.rid or "", chat.rcid or ""]
        else:
            metadata = []
        download_urls: dict[int, str] = {}
        if not _SKIP_2X:
            for i, image in enumerate(response.images):
                token = _image_tokens.pop(image.url, None)
                if token and metadata:
                    logger.info("Requesting 2x download URL for image %d...", i)
                    dl_url = await _fetch_download_url(client, token, prompt, metadata, i)
                    if dl_url:
                        download_urls[i] = dl_url
                        logger.info("Got 2x download URL for image %d", i)
        _image_tokens.clear()  # clean up any leftover tokens
        t = _stage("c8o8Fe (2x url) done", t)

        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        saved = []

        # Resolve the watermark pipeline mode for this request:
        #   • a file uploaded this turn → edit pipeline (margin 96)
        #   • continuation (no file)    → inherit the conversation's recorded mode;
        #                                 foreign cid → "auto" (detect both anchors)
        #   • plain txt2img             → txt pipeline (margin 32)
        input_cid = conversation_id[0] if conversation_id else None
        if resolved_files:
            wm_mode = "edit"
        elif input_cid:
            wm_mode = _get_conv_mode(input_cid) or "auto"
        else:
            wm_mode = "txt"
        applied_mode = wm_mode if wm_mode in ("edit", "txt") else None

        for i, image in enumerate(response.images):
            # Ensure a download timeout even if this image came from the
            # original (non-patched) parser, where session_kwargs is empty.
            try:
                if "timeout" not in getattr(image, "session_kwargs", {}):
                    image.session_kwargs = {**getattr(image, "session_kwargs", {}),
                                            "timeout": DOWNLOAD_TIMEOUT}
            except Exception:
                pass
            # Use 2x upscale URL from c8o8Fe if available
            has_upscale = i in download_urls
            if has_upscale:
                # Use c8o8Fe 2x URL with =s0 for full resolution (not =s2048 which downscales)
                image.url = re.sub(r"=[^/]*$", "", download_urls[i]) + "=s0"
            elif re.search(r"=s\d+(-[a-z0-9]+)*$", image.url):
                # googleusercontent URL with an explicit =sNNNN size suffix: bump to
                # =s0 for full resolution. gg-dl token URLs have no such suffix and
                # reject =s0 with HTTP 400, so we leave those untouched (download as-is,
                # which already returns the full-size image).
                image.url = re.sub(r"=s\d+(-[a-z0-9]+)*$", "=s0", image.url)

            try:
                # full_size=False only when c8o8Fe already gave us a URL with =s0;
                # otherwise library's =s2048 is needed for full-size preview download.
                # Without this gating, an un-upscaled URL with no suffix drops to a
                # ~382px thumbnail instead of the ~896px preview.
                filepath = await image.save(
                    path=str(IMAGES_DIR),
                    filename=f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}.png",
                    verbose=False,
                    full_size=not has_upscale,
                )
            except Exception as save_err:
                logger.warning("Image save failed for %d: %s", i, save_err)
                continue
            t = _stage(f"download+save image {i}", t)

            if not filepath:
                continue

            try:
                rm = _remove_watermark(filepath, mode=wm_mode, upscaled=has_upscale)
                if rm in ("edit", "txt"):
                    applied_mode = rm   # self-learn the mode found by detection
            except Exception as wm_err:
                logger.warning("Watermark removal failed: %s", wm_err)
            t = _stage(f"watermark removal image {i}", t)
            title = getattr(image, "title", None) or f"image_{i}"
            saved.append({"title": title, "path": filepath, "dir": str(IMAGES_DIR)})

        # For response: prefer chat metadata (clean cid/rid/rcid), fall back to raw
        if chat:
            conv_id = [chat.cid or "", chat.rid or "", chat.rcid or ""]
        else:
            conv_id = metadata[:3] if metadata and metadata[0] else None
        # Persist the conversation's pipeline mode so its continuations (which carry
        # no file and run in a fresh process) can pick the watermark spot exactly.
        if conv_id and conv_id[0] and applied_mode:
            _record_conv_mode(conv_id[0], applied_mode)
        result = {
            "text": response.text or "",
            "images_saved_to": str(IMAGES_DIR),
            "images": saved,
            "conversation_id": conv_id,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="gemini_upload_file",
    annotations={
        "title": "Gemini File Upload & Analysis",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def gemini_upload_file(
    file_path: str,
    ctx: Context,
    prompt: str = "Describe this file.",
    model: Optional[str] = None,
) -> str:
    """Upload a file (image, PDF, document, video) to Gemini and ask a question about it.

    Args:
        file_path: Absolute path to the file to upload.
        prompt: Question or instruction about the file
                (e.g. 'What is shown in this image?').
        model: Model name. Defaults to gemini-3.0-flash.

    Returns:
        Gemini's text response about the uploaded file.
    """
    try:
        p = Path(file_path).expanduser().resolve()
        if not p.exists():
            return f"Error: File not found — {p}"

        client = _get_client(ctx)
        response = await client.generate_content(
            prompt, model=model or DEFAULT_MODEL, files=[str(p)]
        )
        return response.text or "(empty response)"

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="gemini_analyze_url",
    annotations={
        "title": "Gemini URL Analysis",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def gemini_analyze_url(
    url: str,
    ctx: Context,
    prompt: str = "Summarize this content.",
    model: Optional[str] = None,
) -> str:
    """Analyze a URL — YouTube videos, webpages, articles, etc.

    Gemini can watch YouTube videos and read webpages, then answer
    questions about their content.

    Args:
        url: The URL to analyze (YouTube, article, webpage, etc.).
        prompt: Question or instruction about the content
                (e.g. 'Summarize this video', 'What are the key points?').
        model: Model name. Defaults to gemini-3.0-flash.

    Returns:
        Gemini's analysis of the URL content.
    """
    try:
        client = _get_client(ctx)
        full_prompt = f"{prompt}\n\n{url}"
        response = await client.generate_content(
            full_prompt, model=model or DEFAULT_MODEL
        )
        return response.text or "(empty response)"
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="gemini_reset",
    annotations={
        "title": "Reset Gemini Client",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gemini_reset(ctx: Context) -> str:
    """Re-initialise the Gemini client (refresh cookies, clear state).

    Use this when you get authentication errors or want a fresh session.

    Returns:
        Confirmation message or error.
    """
    try:
        from gemini_webapi import GeminiClient

        old = _get_client(ctx)
        await old.close()

        psid, psidts = _resolve_cookies()

        account_index = int(os.environ.get("GEMINI_ACCOUNT_INDEX", "0"))
        new_client = GeminiClient(
            secure_1psid=psid, secure_1psidts=psidts or None, account_index=account_index
        )
        await new_client.init(timeout=300, watchdog_timeout=45, auto_close=False, auto_refresh=True)
        _patch_client(new_client)

        ctx.request_context.lifespan_context["gemini_client"] = new_client
        return "Gemini client re-initialised with fresh cookies."

    except Exception as e:
        return _handle_error(e)
