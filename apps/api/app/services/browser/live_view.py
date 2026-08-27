"""Addressing for the API-authenticated browser live view, and the standalone
viewer page a bot user opens.

The live view is served through our API (never the browser host directly), at a
short root path: ``{BROWSER_LIVE_VIEW_BASE_URL or HOST}/live/{session_id}``. In
prod the base is a friendly vhost (browser.heygaia.io) that reverse-proxies to
THIS api service. A logged-in web user watches it through the chat card's canvas
(the card fetches a ``?t=`` token because the host-only session cookie is not
sent cross-origin); a bot user — who has no web session — opens the same URL with
a ``?t=`` takeover token, which serves the self-contained HTML viewer below. Both
drive the same WebSocket the API proxies to the host.
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

from app.config.settings import settings
from app.services.browser.live_code import mint_live_code

_WORDMARK_DATA_URI = "data:image/png;base64," + base64.b64encode(
    (Path(__file__).parent / "assets" / "gaia_wordmark_white.png").read_bytes()
).decode("ascii")

_LIVE_VIEW_PATH_TEMPLATE = "/live/{session_id}"


def _live_view_base() -> str:
    """Public base URL fronting the live-view route (friendly vhost, or HOST)."""
    base: str = settings.BROWSER_LIVE_VIEW_BASE_URL or settings.HOST
    return base.rstrip("/")


def live_view_url(session_id: str) -> str:
    """The public live-view URL for a session (the base the chat card connects to)."""
    return f"{_live_view_base()}{_LIVE_VIEW_PATH_TEMPLATE.format(session_id=session_id)}"


async def create_live_view_link(session_id: str, user_id: str) -> str:
    """A short capability link a bot delivers so ``user_id`` can take over without a web
    login. ``{vhost}/{code}`` when a dedicated live-view vhost is configured (the vhost
    rewrites ``/{code}`` to the app's ``/live/{code}``), else ``{host}/live/{code}``. The
    code maps to the session + owner in Redis — no session id or token in the URL."""
    code = await mint_live_code(session_id, user_id)
    base = _live_view_base()
    if settings.BROWSER_LIVE_VIEW_BASE_URL:
        return f"{base}/{code}"
    return f"{base}/live/{code}"


def render_live_view_page(session_id: str) -> str:
    """Self-contained HTML viewer served to a bot user opening the tokened link.

    Reads its own URL to open the WebSocket (carrying the ``?t=`` token or the
    same-origin session cookie), draws each JPEG frame onto a canvas, and forwards
    pointer/keyboard input as CDP-shaped ``mouse``/``key`` messages.
    """
    safe_session = html.escape(session_id)
    return _VIEWER_TEMPLATE.replace("__SESSION_ID__", safe_session).replace(
        "__WORDMARK__", _WORDMARK_DATA_URI
    )


# Kept byte-for-byte parallel with the React canvas in BrowserTaskSection.tsx:
# both translate DOM pointer/key events into the CDP shapes screencast.py applies.
_VIEWER_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>GAIA \u2014 Live browser (__SESSION_ID__)</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #09090b; color: #e4e4e7;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
  body { display: flex; flex-direction: column; height: 100vh; }
  header { flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; padding: 12px 20px; }
  .brand { display: flex; align-items: center; gap: 10px; }
  .brand img { height: 24px; display: block; }
  .status { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: #a1a1aa; }
  .status .dot { width: 8px; height: 8px; border-radius: 999px; background: #71717a; }
  .status.live { color: #d4d4d8; }
  .status.live .dot { background: #22c55e; }
  .status.connecting .dot { background: #f59e0b; }
  .status.ended .dot { background: #ef4444; }
  main { flex: 1 1 auto; min-height: 0; display: flex; align-items: center; justify-content: center; padding: 0 14px 14px; }
  #screen { max-width: 100%; max-height: 100%; border-radius: 10px;
    box-shadow: 0 0 0 1px rgba(255,255,255,0.07); background: #18181b;
    cursor: crosshair; outline: none; touch-action: none; }
</style>
</head>
<body>
<header>
  <div class="brand"><img src="__WORDMARK__" alt="GAIA" /></div>
  <div id="status" class="status connecting"><span class="dot"></span><span id="statusLabel">Connecting\u2026</span></div>
</header>
<main><canvas id="screen" width="1280" height="800" tabindex="0"></canvas></main>
<script>
(function () {
  var canvas = document.getElementById("screen");
  var ctx = canvas.getContext("2d");
  var statusEl = document.getElementById("status");
  var statusLabel = document.getElementById("statusLabel");
  function setStatus(state, label) { statusEl.className = "status " + state; statusLabel.textContent = label; }
  // cssW/H: the page's CSS pixel size (per-frame metadata) \u2014 the space CDP input
  // expects. The frame bitmap may be a downscaled rendering of it, so pointer
  // math uses THIS, never the bitmap size, or clicks land short of the target.
  var cssW = 1280, cssH = 800;
  var ws = new WebSocket(location.href.replace(/^http/, "ws"));
  ws.onopen = function () { setStatus("live", "Live \u2014 you're in control"); canvas.focus(); };
  ws.onclose = function () { setStatus("ended", "Session ended"); };
  ws.onerror = function () { setStatus("ended", "Connection error"); };
  var img = new Image();
  img.onload = function () {
    var w = img.naturalWidth, h = img.naturalHeight;
    if (!w || !h) return;
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    ctx.drawImage(img, 0, 0, w, h);
  };
  ws.onmessage = function (ev) {
    var msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.type !== "frame") return;
    if (msg.cssWidth && msg.cssHeight) { cssW = msg.cssWidth; cssH = msg.cssHeight; }
    img.src = "data:image/" + (msg.format || "jpeg") + ";base64," + msg.data;
  };
  function send(obj) { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj)); }
  function toPagePoint(e) {
    var r = canvas.getBoundingClientRect();
    return {
      x: Math.round((e.clientX - r.left) * (cssW / r.width)),
      y: Math.round((e.clientY - r.top) * (cssH / r.height))
    };
  }
  // CDP modifier bitmask (Alt=1, Ctrl=2, Meta=4, Shift=8) \u2014 without it,
  // Shift-selection and Cmd/Ctrl shortcuts silently no-op.
  function toModifiers(e) {
    return (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);
  }
  var BUTTONS = ["left", "middle", "right"];
  // Coalesce mousemove to one message per animation frame so press/release
  // events never queue behind a flood of stale moves.
  var pendingMove = null, moveRaf = 0;
  function flushMove() {
    moveRaf = 0;
    if (pendingMove) { send(pendingMove); pendingMove = null; }
  }
  canvas.addEventListener("mousemove", function (e) {
    var p = toPagePoint(e);
    pendingMove = { type: "mouse", event: "mouseMoved", x: p.x, y: p.y, buttons: e.buttons, modifiers: toModifiers(e) };
    if (!moveRaf) moveRaf = requestAnimationFrame(flushMove);
  });
  canvas.addEventListener("mousedown", function (e) {
    e.preventDefault(); canvas.focus(); flushMove(); var p = toPagePoint(e);
    send({ type: "mouse", event: "mousePressed", x: p.x, y: p.y, button: BUTTONS[e.button] || "left", buttons: e.buttons, clickCount: e.detail || 1, modifiers: toModifiers(e) });
  });
  canvas.addEventListener("mouseup", function (e) {
    e.preventDefault(); flushMove(); var p = toPagePoint(e);
    send({ type: "mouse", event: "mouseReleased", x: p.x, y: p.y, button: BUTTONS[e.button] || "left", buttons: e.buttons, clickCount: e.detail || 1, modifiers: toModifiers(e) });
  });
  canvas.addEventListener("contextmenu", function (e) { e.preventDefault(); });
  canvas.addEventListener("wheel", function (e) {
    e.preventDefault(); var p = toPagePoint(e);
    send({ type: "mouse", event: "mouseWheel", x: p.x, y: p.y, deltaX: e.deltaX, deltaY: e.deltaY, modifiers: toModifiers(e) });
  }, { passive: false });
  function keyEvent(kind, e) {
    // CDP fires a key's default action (submit a form, insert a newline) only
    // when `text` is set: printables send themselves, Enter must send "\r".
    // A char typed with Ctrl/Meta held is a shortcut, not text.
    var printable = e.key && e.key.length === 1 && !e.ctrlKey && !e.metaKey;
    var msg = { type: "key", event: kind, key: e.key, code: e.code, windowsVirtualKeyCode: e.keyCode, nativeVirtualKeyCode: e.keyCode, modifiers: toModifiers(e) };
    if (kind === "keyDown" && printable) msg.text = e.key;
    if (kind === "keyDown" && e.key === "Enter") msg.text = "\\r";
    send(msg);
  }
  canvas.addEventListener("keydown", function (e) { e.preventDefault(); keyEvent("keyDown", e); });
  canvas.addEventListener("keyup", function (e) { e.preventDefault(); keyEvent("keyUp", e); });
})();
</script>
</body>
</html>"""
