import { useCallback, useEffect, useRef, useState } from "react";
import type {
  BrowserFrameMessage,
  BrowserLiveInputMessage,
} from "@/types/features/browserTaskTypes";

export type LiveStatus = "connecting" | "live" | "closed" | "error";

const CDP_MOUSE_BUTTONS = ["left", "middle", "right"] as const;

// Streams JPEG frames from the live-view WebSocket onto a canvas and, when
// interactive, forwards pointer/keyboard input as the CDP-shaped messages the
// browser host applies. Kept parallel with the standalone viewer the API serves
// (services/browser/live_view.py) — same event translation, two runtimes.
export function useLiveBrowser(socketUrl: string | null, interactive: boolean) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const frameSizeRef = useRef<{ w: number; h: number }>({ w: 1280, h: 720 });
  const [status, setStatus] = useState<LiveStatus>("connecting");

  const send = useCallback((msg: BrowserLiveInputMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }, []);

  useEffect(() => {
    if (!socketUrl) return undefined;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return undefined;

    setStatus("connecting");
    const ws = new WebSocket(socketUrl);
    wsRef.current = ws;
    const img = new window.Image();

    img.onload = () => {
      const w = img.naturalWidth || frameSizeRef.current.w;
      const h = img.naturalHeight || frameSizeRef.current.h;
      frameSizeRef.current = { w, h };
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      ctx.drawImage(img, 0, 0, w, h);
    };

    ws.onopen = () => setStatus("live");
    ws.onerror = () => setStatus("error");
    ws.onclose = () => setStatus("closed");
    ws.onmessage = (ev: MessageEvent<string>) => {
      let msg: BrowserFrameMessage;
      try {
        msg = JSON.parse(ev.data) as BrowserFrameMessage;
      } catch {
        return;
      }
      if (msg.type === "frame") img.src = `data:image/jpeg;base64,${msg.data}`;
    };

    return () => {
      ws.onopen = null;
      ws.onerror = null;
      ws.onclose = null;
      ws.onmessage = null;
      ws.close();
      wsRef.current = null;
    };
  }, [socketUrl]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!interactive || !socketUrl || !canvas) return undefined;

    const toPoint = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const { w, h } = frameSizeRef.current;
      return {
        x: Math.round((e.clientX - rect.left) * (w / rect.width)),
        y: Math.round((e.clientY - rect.top) * (h / rect.height)),
      };
    };

    const onMove = (e: MouseEvent) => {
      const p = toPoint(e);
      send({
        type: "mouse",
        event: "mouseMoved",
        x: p.x,
        y: p.y,
        buttons: e.buttons,
      });
    };
    const onDown = (e: MouseEvent) => {
      e.preventDefault();
      canvas.focus();
      const p = toPoint(e);
      send({
        type: "mouse",
        event: "mousePressed",
        x: p.x,
        y: p.y,
        button: CDP_MOUSE_BUTTONS[e.button] ?? "left",
        buttons: e.buttons,
        clickCount: e.detail || 1,
      });
    };
    const onUp = (e: MouseEvent) => {
      e.preventDefault();
      const p = toPoint(e);
      send({
        type: "mouse",
        event: "mouseReleased",
        x: p.x,
        y: p.y,
        button: CDP_MOUSE_BUTTONS[e.button] ?? "left",
        buttons: e.buttons,
        clickCount: e.detail || 1,
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
      });
    };
    const onKeyDown = (e: KeyboardEvent) => {
      e.preventDefault();
      // CDP only fires a key's default action (submit a form, insert a newline)
      // when `text` is set. A single character sends itself; Enter must send the
      // carriage return "\r" or nothing happens — verified against a real page.
      // Other non-printable keys (Tab, Backspace, arrows) act on their virtual
      // key code alone and take no text.
      const text =
        e.key.length === 1 ? e.key : e.key === "Enter" ? "\r" : undefined;
      send({
        type: "key",
        event: "keyDown",
        key: e.key,
        code: e.code,
        text,
        windowsVirtualKeyCode: e.keyCode,
        nativeVirtualKeyCode: e.keyCode,
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
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("mousedown", onDown);
      canvas.removeEventListener("mouseup", onUp);
      canvas.removeEventListener("contextmenu", onContext);
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("keydown", onKeyDown);
      canvas.removeEventListener("keyup", onKeyUp);
    };
  }, [interactive, socketUrl, send]);

  return { canvasRef, status };
}
