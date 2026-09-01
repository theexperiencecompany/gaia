import { useCallback, useEffect, useRef, useState } from "react";
import type {
  BrowserFrameMessage,
  BrowserLiveInputMessage,
} from "@/types/features/browserTaskTypes";

export type LiveStatus = "connecting" | "live" | "closed";

const CDP_MOUSE_BUTTONS = ["left", "middle", "right"] as const;

const RECONNECT_ATTEMPTS = 3;
const RECONNECT_DELAY_MS = 1500;

// Streams JPEG frames from the live-view WebSocket onto a canvas and, when
// interactive, forwards pointer/keyboard input as the CDP-shaped messages the
// browser host applies. Kept parallel with the standalone viewer the API serves
// (services/browser/live_view.py) — same event translation, two runtimes.
export function useLiveBrowser(socketUrl: string | null, interactive: boolean) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  // Page CSS size — the coordinate space CDP input expects. The frame bitmap can
  // be a downscaled rendering of it, so pointer math must use THIS, never the
  // bitmap size, or clicks land short of the target.
  const cssSizeRef = useRef<{ w: number; h: number }>({ w: 1280, h: 800 });
  const [status, setStatus] = useState<LiveStatus>("connecting");
  // Latest page identity off the frame stream — drives the panel's tab + URL bar.
  const [page, setPage] = useState<{
    url: string | null;
    title: string | null;
    favicon: string | null;
  }>({ url: null, title: null, favicon: null });

  const send = useCallback((msg: BrowserLiveInputMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }, []);

  useEffect(() => {
    if (!socketUrl) return undefined;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return undefined;

    const img = new window.Image();
    img.onload = () => {
      const w = img.naturalWidth;
      const h = img.naturalHeight;
      if (!w || !h) return;
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      ctx.drawImage(img, 0, 0, w, h);
    };

    // A dropped socket (API restart, network blip) is retried a few times
    // before the view is declared over — a momentary drop must not strand the
    // user on "Session ended" while the browser is still alive. A session that
    // is actually gone rejects every reconnect, and we settle on "closed".
    let disposed = false;
    let attemptsLeft = RECONNECT_ATTEMPTS;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      setStatus("connecting");
      const ws = new WebSocket(socketUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        attemptsLeft = RECONNECT_ATTEMPTS;
        setStatus("live");
      };
      ws.onclose = () => {
        if (disposed) return;
        if (attemptsLeft > 0) {
          attemptsLeft -= 1;
          retryTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        } else {
          setStatus("closed");
        }
      };
      ws.onmessage = (ev: MessageEvent<string>) => {
        let msg: BrowserFrameMessage;
        try {
          msg = JSON.parse(ev.data) as BrowserFrameMessage;
        } catch {
          return;
        }
        if (msg.type !== "frame") return;
        if (msg.cssWidth && msg.cssHeight) {
          cssSizeRef.current = { w: msg.cssWidth, h: msg.cssHeight };
        }
        setPage((prev) =>
          prev.url === (msg.url ?? null) &&
          prev.title === (msg.title ?? null) &&
          prev.favicon === (msg.favicon ?? null)
            ? prev
            : {
                url: msg.url ?? null,
                title: msg.title ?? null,
                favicon: msg.favicon ?? null,
              },
        );
        img.src = `data:image/jpeg;base64,${msg.data}`;
      };
    };
    connect();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      const ws = wsRef.current;
      if (ws) {
        ws.onopen = null;
        ws.onerror = null;
        ws.onclose = null;
        ws.onmessage = null;
        ws.close();
      }
      wsRef.current = null;
    };
  }, [socketUrl]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!interactive || !socketUrl || !canvas) return undefined;

    const toPoint = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const { w, h } = cssSizeRef.current;
      return {
        x: Math.round((e.clientX - rect.left) * (w / rect.width)),
        y: Math.round((e.clientY - rect.top) * (h / rect.height)),
      };
    };
    // CDP modifier bitmask (Alt=1, Ctrl=2, Meta=4, Shift=8) — without it,
    // Shift-selection, capital shortcuts and Cmd/Ctrl combos silently no-op.
    const toModifiers = (e: MouseEvent | KeyboardEvent) =>
      (e.altKey ? 1 : 0) |
      (e.ctrlKey ? 2 : 0) |
      (e.metaKey ? 4 : 0) |
      (e.shiftKey ? 8 : 0);

    // Coalesce mousemove to one message per animation frame: a raw stream (~60+
    // events/s, more on high-Hz mice) queues behind the WebSocket + CDP hop and
    // delays the press/release events that actually matter.
    let pendingMove: BrowserLiveInputMessage | null = null;
    let moveRaf = 0;
    const flushMove = () => {
      moveRaf = 0;
      if (pendingMove) {
        send(pendingMove);
        pendingMove = null;
      }
    };
    const onMove = (e: MouseEvent) => {
      const p = toPoint(e);
      pendingMove = {
        type: "mouse",
        event: "mouseMoved",
        x: p.x,
        y: p.y,
        buttons: e.buttons,
        modifiers: toModifiers(e),
      };
      if (!moveRaf) moveRaf = requestAnimationFrame(flushMove);
    };
    const onDown = (e: MouseEvent) => {
      e.preventDefault();
      canvas.focus();
      flushMove();
      const p = toPoint(e);
      send({
        type: "mouse",
        event: "mousePressed",
        x: p.x,
        y: p.y,
        button: CDP_MOUSE_BUTTONS[e.button] ?? "left",
        buttons: e.buttons,
        clickCount: e.detail || 1,
        modifiers: toModifiers(e),
      });
    };
    const onUp = (e: MouseEvent) => {
      e.preventDefault();
      flushMove();
      const p = toPoint(e);
      send({
        type: "mouse",
        event: "mouseReleased",
        x: p.x,
        y: p.y,
        button: CDP_MOUSE_BUTTONS[e.button] ?? "left",
        buttons: e.buttons,
        clickCount: e.detail || 1,
        modifiers: toModifiers(e),
      });
    };
    const onContext = (e: MouseEvent) => e.preventDefault();
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const p = toPoint(e);
      send({
        type: "mouse",
        event: "mouseWheel",
        x: p.x,
        y: p.y,
        deltaX: e.deltaX,
        deltaY: e.deltaY,
        modifiers: toModifiers(e),
      });
    };
    const onKeyDown = (e: KeyboardEvent) => {
      e.preventDefault();
      // CDP only fires a key's default action (submit a form, insert a newline)
      // when `text` is set. A single character sends itself; Enter must send the
      // carriage return "\r" or nothing happens — verified against a real page.
      // Other non-printable keys (Tab, Backspace, arrows) act on their virtual
      // key code alone and take no text. A char typed with Ctrl/Meta held is a
      // shortcut, not text — sending text would insert the letter too.
      const printable = e.key.length === 1 && !e.ctrlKey && !e.metaKey;
      const text = printable ? e.key : e.key === "Enter" ? "\r" : undefined;
      send({
        type: "key",
        event: "keyDown",
        key: e.key,
        code: e.code,
        text,
        windowsVirtualKeyCode: e.keyCode,
        nativeVirtualKeyCode: e.keyCode,
        modifiers: toModifiers(e),
      });
    };
    const onKeyUp = (e: KeyboardEvent) => {
      e.preventDefault();
      send({
        type: "key",
        event: "keyUp",
        key: e.key,
        code: e.code,
        windowsVirtualKeyCode: e.keyCode,
        nativeVirtualKeyCode: e.keyCode,
        modifiers: toModifiers(e),
      });
    };

    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mousedown", onDown);
    canvas.addEventListener("mouseup", onUp);
    canvas.addEventListener("contextmenu", onContext);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("keydown", onKeyDown);
    canvas.addEventListener("keyup", onKeyUp);
    return () => {
      if (moveRaf) cancelAnimationFrame(moveRaf);
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("mousedown", onDown);
      canvas.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("contextmenu", onContext);
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("keydown", onKeyDown);
      canvas.removeEventListener("keyup", onKeyUp);
    };
  }, [interactive, socketUrl, send]);

  return { canvasRef, status, page };
}
