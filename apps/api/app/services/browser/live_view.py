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
<title>GAIA \u2014 Live browser (__SESSION_ID__)</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #09090b; color: #e4e4e7;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
  body { display: flex; flex-direction: column; align-items: center; padding: 16px 20px; gap: 14px; }
  header { width: 100%; max-width: 1280px; display: flex; align-items: center; justify-content: space-between; }
  .brand { display: flex; align-items: center; gap: 10px; }
  .brand svg { width: 22px; height: 22px; display: block; }
  .brand span { font-weight: 600; letter-spacing: .16em; font-size: 15px; color: #fafafa; }
  .status { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: #a1a1aa; }
  .status .dot { width: 8px; height: 8px; border-radius: 999px; background: #71717a; }
  .status.live { color: #d4d4d8; }
  .status.live .dot { background: #22c55e; }
  .status.connecting .dot { background: #f59e0b; }
  .status.ended .dot { background: #ef4444; }
  #screen { max-width: 100%; max-height: 85vh; border-radius: 12px;
    box-shadow: 0 0 0 1px rgba(255,255,255,0.07); background: #18181b;
    cursor: crosshair; outline: none; touch-action: none; }
  footer { font-size: 12px; color: #52525b; }
</style>
</head>
<body>
<header>
  <div class="brand"><svg width="22" height="22" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2441.45 2400"> <g id="Layer_1" data-name="Layer 1"> <g> <path fill="#059cda" d="M2294.76,754.91c52.05,40.47,71.76,93.13,90.55,154.88,197.81,650.16-261.39,1391.76-935.7,1488.14-21.8,3.12-71.79-10.84-92.82-19.75,56.56,5.45,107.78-12.37,158.53-34.53,231.32-101.03,347.34-289.02,356.36-540.29,2.82-78.64-6.26-139.1-15.36-215-.17-1.41.2-2.97,0-4.36,10.57.02,20.27-4.54,29.83-8.35,160.58-63.98,349.04-190.78,416.22-356.05,43.56-107.16,57.02-244.62,35.39-358.23-7.47-39.21-20.03-73.69-42.99-106.46Z"/> <path fill="#059cda" d="M148.33,759.27c-66.61,93.84-55.47,288.96-25.54,395.37,53.37,189.75,213.09,315.21,384.68,396.32,24.67,11.66,53.12,24.23,79.31,30.86l2.18,4.36c-1.66,6.59-5.46,14.39-6.37,20.9-21.41,152.78-12.44,330.19,53.98,471.49,64.34,136.89,285.66,307.41,441.01,301.8-49.61,22.02-102.16,12.47-153.1,1.5C286.1,2244.42-134.68,1528.46,62.69,901.61c14.68-46.61,31.08-89.68,64.6-126.3l21.04-16.04Z"/> <path fill="#059cda" d="M290.12,514.91c5.34-52.72,39.4-94.96,73.04-133.12,426.06-483.19,1252.51-488.16,1697.43-27.57,43.5,45.03,89.12,97.14,98.92,160.69-42.11-71.19-117.1-125.07-189.73-162.59-204.09-105.44-387.41-82.71-583.93,24.76-47.65,26.06-104.22,61.67-145.71,96.44-4.4,3.69-8.87,8.24-12.06,13.03h-6.54c-29.89-30.53-68.56-56.62-104.89-79.45-149.66-94.07-319.77-154.18-497.17-109.29-97.33,24.63-290.5,119.22-329.37,217.1ZM547.52,233.44c1.45,1.35,8.65-1.02,8.67-3.26.06-6.51-12.83-.61-8.67,3.26Z"/> <path fill="#0f537c" d="M1856.31,1584c-5.67-40.19-5.48-89.09-4.45-129.91,5.15-203.81,70.21-488.23,209.55-643.49,58.33-65,152.18-118.81,233.35-55.69,22.96,32.77,35.52,67.24,42.99,106.46,21.63,113.62,8.17,251.08-35.39,358.23-67.18,165.27-255.63,292.07-416.22,356.05-9.56,3.81-19.26,8.37-29.83,8.35Z"/> <path fill="#0f537c" d="M588.96,1586.18c131.16,59.49,255.06,148.11,356.9,249.61,95.16,94.85,235.97,275.99,227.8,417.03-3,51.75-34.83,114.47-89.54,125.35-1.76.35-3.74-.05-4.36,2.18-.72.06-1.46-.03-2.18,0-155.36,5.62-376.67-164.91-441.01-301.8-66.41-141.3-75.38-318.71-53.98-471.49.91-6.51,4.71-14.31,6.37-20.9Z"/> <path fill="#0f537c" d="M1221.55,486.55c-117.35,84.94-258.36,147.92-398.71,184.83-132.56,34.87-378.72,69.78-490.24-27.69-32.68-28.56-59.45-86.04-42.48-128.78,38.87-97.88,232.04-192.47,329.37-217.1,177.4-44.9,347.51,15.22,497.17,109.29,36.33,22.84,75,48.92,104.89,79.45Z"/> <path fill="#02bdff" d="M1856.31,1588.36c9.1,75.9,18.18,136.36,15.36,215-9.02,251.27-125.04,439.26-356.36,540.29-50.75,22.16-101.96,39.98-158.53,34.53-126.94-53.77-87.47-203.8-38.27-301.19,95.44-188.97,303.5-371.35,490.07-467.64,15.29-7.89,31.28-16.21,47.73-20.99Z"/> <path fill="#02bdff" d="M148.33,759.27c1.09-1.54,1.16-4.77,2.73-5.94,51.61-33.19,101.95-35.59,156.6-6.16,144.17,77.63,232.06,337.61,261.03,489.46,21.52,112.79,30.38,230.97,18.09,345.18-26.19-6.63-54.64-19.2-79.31-30.86-171.59-81.11-331.31-206.57-384.68-396.32-29.93-106.41-41.07-301.52,25.54-395.37Z"/> <path fill="#02bdff" d="M2159.52,514.91c18.04,116.94-78.85,167.98-178.46,184.77-146.36,24.67-319.01-11.4-457.43-60.36-103.63-36.66-207.05-87.74-295.53-152.77,3.19-4.79,7.66-9.34,12.06-13.03,41.49-34.77,98.06-70.38,145.71-96.44,196.52-107.47,379.84-130.2,583.93-24.76,72.63,37.52,147.62,91.41,189.73,162.59Z"/> <path fill="#059cda" d="M1084.12,2378.18c-.68,2.09-2.49,2.04-4.36,2.18.63-2.23,2.6-1.83,4.36-2.18Z"/> <path fill="#0f537c" d="M547.52,233.44c-4.16-3.87,8.74-9.77,8.67-3.26-.02,2.24-7.22,4.61-8.67,3.26Z"/> </g> </g> <g id="Layer_2" data-name="Layer 2"> <path fill="#059cda" d="M568.24,221.98c.9,7.44,1.13,14.95.68,22.43-.07,1.15-.25,2.47-1.22,3.09-.59.38-1.34.39-2.05.4-7.23.02-14.47.03-21.7.05-2.1,0-4.57-.18-5.69-1.96-.61-.98-.64-2.2-.65-3.35-.01-2.17-.03-4.33-.04-6.5-.07-11.62,30.13-18.53,30.67-14.16Z"/> </g> </svg><span>GAIA</span></div>
  <div id="status" class="status connecting"><span class="dot"></span><span id="statusLabel">Connecting\u2026</span></div>
</header>
<canvas id="screen" width="1280" height="800" tabindex="0"></canvas>
<footer>You have live control of this browser</footer>
<script>
(function () {
  var canvas = document.getElementById("screen");
  var ctx = canvas.getContext("2d");
  var statusEl = document.getElementById("status");
  var statusLabel = document.getElementById("statusLabel");
  function setStatus(state, label) { statusEl.className = "status " + state; statusLabel.textContent = label; }
  var frameW = 1280, frameH = 800;
  var ws = new WebSocket(location.href.replace(/^http/, "ws"));
  ws.onopen = function () { setStatus("live", "Live \u2014 you're in control"); canvas.focus(); };
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
