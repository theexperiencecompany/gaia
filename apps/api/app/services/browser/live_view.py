"""Addressing for the API-authenticated browser live view, and the standalone
viewer page a bot user opens.

The live view is served through our API (never the browser host directly):
``{HOST}/api/v1/browser/sessions/{id}/live-view``. A logged-in web user watches
it through the chat card's canvas; a bot user — who has no web session — opens the
same URL with a ``?t=`` takeover token, which serves the self-contained HTML
viewer below. Both drive the same WebSocket the API proxies to the host.
"""

from __future__ import annotations

import html

from app.config.settings import settings
from app.services.browser.takeover_token import create_takeover_token

_LIVE_VIEW_PATH_TEMPLATE = "/api/v1/browser/sessions/{session_id}/live-view"


def live_view_url(session_id: str) -> str:
    """The public API live-view URL for a session (used by the chat card)."""
    base = settings.HOST.rstrip("/")
    return f"{base}{_LIVE_VIEW_PATH_TEMPLATE.format(session_id=session_id)}"


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
  html, body { margin: 0; height: 100%; background: #09090b; color: #e4e4e7;
    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }
  body { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 16px; box-sizing: border-box; }
  #status { font-size: 13px; color: #a1a1aa; }
  #screen { max-width: 100%; max-height: 82vh; border-radius: 12px;
    box-shadow: 0 0 0 1px rgba(255,255,255,0.08); background: #18181b;
    cursor: crosshair; outline: none; touch-action: none; }
</style>
</head>
<body>
<div id="status">Connecting…</div>
<canvas id="screen" width="1280" height="720" tabindex="0"></canvas>
<script>
(function () {
  var canvas = document.getElementById("screen");
  var ctx = canvas.getContext("2d");
  var statusEl = document.getElementById("status");
  var frameW = 1280, frameH = 720;
  var ws = new WebSocket(location.href.replace(/^http/, "ws"));
  ws.onopen = function () { statusEl.textContent = "Live — you're in control"; canvas.focus(); };
  ws.onclose = function () { statusEl.textContent = "Session ended"; };
  ws.onerror = function () { statusEl.textContent = "Connection error"; };
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
