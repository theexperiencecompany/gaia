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

import html

from app.config.settings import settings
from app.services.browser.takeover_token import create_takeover_token

_LIVE_VIEW_PATH_TEMPLATE = "/live/{session_id}"


def _live_view_base() -> str:
    """Public base URL fronting the live-view route (friendly vhost, or HOST)."""
    base: str = settings.BROWSER_LIVE_VIEW_BASE_URL or settings.HOST
    return base.rstrip("/")


def live_view_url(session_id: str) -> str:
    """The public live-view URL for a session (the base the chat card connects to)."""
    return f"{_live_view_base()}{_LIVE_VIEW_PATH_TEMPLATE.format(session_id=session_id)}"


def live_view_link_with_token(session_id: str, user_id: str) -> str:
    """A tokened live-view link a bot delivers so ``user_id`` can take over without a web login."""
    token = create_takeover_token(session_id, user_id)
    return f"{live_view_url(session_id)}?t={token}"


def render_live_view_page(session_id: str) -> str:
    """Self-contained HTML viewer served to a bot user opening the tokened link.

    Reads its own URL to open the WebSocket (carrying the ``?t=`` token or the
    same-origin session cookie), draws each JPEG frame onto a canvas, and forwards
    pointer/keyboard input as CDP-shaped ``mouse``/``key`` messages.
    """
    safe_session = html.escape(session_id)
    return _VIEWER_TEMPLATE.replace("__SESSION_ID__", safe_session)


# Kept byte-for-byte parallel with the React canvas in BrowserTaskSection.tsx:
# both translate DOM pointer/key events into the CDP shapes screencast.py applies.
_VIEWER_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>GAIA — Live browser (__SESSION_ID__)</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #09090b; color: #e4e4e7;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
  body { display: flex; flex-direction: column; align-items: center; padding: 16px; gap: 14px; }
  header { width: 100%; max-width: 1280px; display: flex; align-items: center; justify-content: space-between; }
  .brand { display: flex; align-items: center; gap: 9px; font-weight: 650; letter-spacing: .09em; font-size: 14px; color: #fafafa; }
  .brand svg { display: block; }
  .chip { display: inline-flex; align-items: center; gap: 7px; padding: 6px 13px; border-radius: 999px;
    font-size: 12.5px; font-weight: 500; color: #d4d4d8;
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.09); }
  .chip .dot { width: 8px; height: 8px; border-radius: 999px; background: #a1a1aa; }
  .chip.live { color: #dcfce7; background: rgba(34,197,94,0.12); border-color: rgba(34,197,94,0.35); }
  .chip.live .dot { background: #22c55e; box-shadow: 0 0 0 3px rgba(34,197,94,0.22); animation: pulse 2s infinite; }
  .chip.connecting { color: #fde68a; background: rgba(245,158,11,0.12); border-color: rgba(245,158,11,0.35); }
  .chip.connecting .dot { background: #f59e0b; }
  .chip.ended { color: #fecaca; background: rgba(239,68,68,0.12); border-color: rgba(239,68,68,0.35); }
  .chip.ended .dot { background: #ef4444; }
  @keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .5 } }
  #screen { max-width: 100%; max-height: 84vh; border-radius: 14px;
    box-shadow: 0 0 0 1px rgba(255,255,255,0.08), 0 24px 64px -24px rgba(0,0,0,0.7); background: #18181b;
    cursor: crosshair; outline: none; touch-action: none; }
  footer { font-size: 11.5px; color: #52525b; letter-spacing: .02em; }
</style>
</head>
<body>
<header>
  <div class="brand">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="#8b5cf6" stroke-width="2"></circle>
      <circle cx="12" cy="12" r="3.4" fill="#8b5cf6"></circle>
    </svg>
    <span>GAIA</span>
  </div>
  <div id="status" class="chip connecting"><span class="dot"></span><span id="statusLabel">Connecting…</span></div>
</header>
<canvas id="screen" width="1280" height="800" tabindex="0"></canvas>
<footer>You have live control of this browser</footer>
<script>
(function () {
  var canvas = document.getElementById("screen");
  var ctx = canvas.getContext("2d");
  var statusEl = document.getElementById("status");
  var statusLabel = document.getElementById("statusLabel");
  function setStatus(state, label) { statusEl.className = "chip " + state; statusLabel.textContent = label; }
  var frameW = 1280, frameH = 800;
  var ws = new WebSocket(location.href.replace(/^http/, "ws"));
  ws.onopen = function () { setStatus("live", "Live — you're in control"); canvas.focus(); };
  ws.onclose = function () { setStatus("ended", "Session ended"); };
  ws.onerror = function () { setStatus("ended", "Connection error"); };
  var img = new Image();
  img.onload = function () {
    frameW = img.naturalWidth || frameW; frameH = img.naturalHeight || frameH;
    if (canvas.width !== frameW || canvas.height !== frameH) { canvas.width = frameW; canvas.height = frameH; }
    ctx.drawImage(img, 0, 0, frameW, frameH);
  };
  ws.onmessage = function (ev) {
    var msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    if (msg.type === "frame") { img.src = "data:image/jpeg;base64," + msg.data; }
  };
  function send(obj) { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj)); }
  function toFramePoint(e) {
    var r = canvas.getBoundingClientRect();
    return {
      x: Math.round((e.clientX - r.left) * (frameW / r.width)),
      y: Math.round((e.clientY - r.top) * (frameH / r.height))
    };
  }
  var BUTTONS = ["left", "middle", "right"];
  canvas.addEventListener("mousemove", function (e) {
    var p = toFramePoint(e); send({ type: "mouse", event: "mouseMoved", x: p.x, y: p.y, buttons: e.buttons });
  });
  canvas.addEventListener("mousedown", function (e) {
    e.preventDefault(); canvas.focus(); var p = toFramePoint(e);
    send({ type: "mouse", event: "mousePressed", x: p.x, y: p.y, button: BUTTONS[e.button] || "left", buttons: e.buttons, clickCount: e.detail || 1 });
  });
  canvas.addEventListener("mouseup", function (e) {
    e.preventDefault(); var p = toFramePoint(e);
    send({ type: "mouse", event: "mouseReleased", x: p.x, y: p.y, button: BUTTONS[e.button] || "left", buttons: e.buttons, clickCount: e.detail || 1 });
  });
  canvas.addEventListener("contextmenu", function (e) { e.preventDefault(); });
  canvas.addEventListener("wheel", function (e) {
    e.preventDefault(); var p = toFramePoint(e);
    send({ type: "mouse", event: "mouseWheel", x: p.x, y: p.y, deltaX: e.deltaX, deltaY: e.deltaY });
  }, { passive: false });
  function keyEvent(kind, e) {
    var printable = e.key && e.key.length === 1;
    var msg = { type: "key", event: kind, key: e.key, code: e.code, windowsVirtualKeyCode: e.keyCode, nativeVirtualKeyCode: e.keyCode };
    if (kind === "keyDown" && printable) msg.text = e.key;
    send(msg);
  }
  canvas.addEventListener("keydown", function (e) { e.preventDefault(); keyEvent("keyDown", e); });
  canvas.addEventListener("keyup", function (e) { e.preventDefault(); keyEvent("keyUp", e); });
})();
</script>
</body>
</html>"""
