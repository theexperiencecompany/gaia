import { useCallback, useEffect, useRef, useState } from "react";
import type {
  BrowserFrameMessage,
  BrowserLiveInputMessage,
} from "@/types/features/browserTaskTypes";
import { useLiveInput } from "./useLiveInput";

export type LiveStatus = "connecting" | "live" | "closed";

export type LiveBrowser = ReturnType<typeof useLiveBrowser>;

const RECONNECT_ATTEMPTS = 3;
const RECONNECT_DELAY_MS = 1500;

/**
 * Streams live-view JPEG frames onto a canvas and, when interactive, forwards
 * the user's input (see useLiveInput). A dropped socket asks `onDropped` for a
 * fresh URL and is redialled a few times; a session that refuses every redial
 * settles on "closed". A new `socketUrl` always dials at once.
 */
export function useLiveBrowser(
  socketUrl: string | null,
  interactive: boolean,
  onDropped?: () => void,
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // State, not a ref: the keyboard input mounts later than the canvas, and
  // useLiveInput binds to it when it does.
  const [keyboard, keyboardRef] = useState<HTMLInputElement | null>(null);
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

  // Read through a ref so a parent passing a new closure never redials.
  const onDroppedRef = useRef(onDropped);
  useEffect(() => {
    onDroppedRef.current = onDropped;
  }, [onDropped]);

  const attemptsLeftRef = useRef(RECONNECT_ATTEMPTS);
  // One dial per value: a new URL dials at once, a retry of the same URL is a
  // new attempt object, so either way the effect below runs again.
  const [dial, setDial] = useState({ url: socketUrl, attempt: 0 });
  if (dial.url !== socketUrl) setDial({ url: socketUrl, attempt: 0 });

  useEffect(() => {
    const url = dial.url;
    if (!url) return undefined;

    // The canvas is looked up per frame: a surface may move it (inline to a
    // full-screen modal) while the socket stays up.
    const img = new window.Image();
    img.onload = () => {
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      const w = img.naturalWidth;
      const h = img.naturalHeight;
      if (!canvas || !ctx || !w || !h) return;
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      ctx.drawImage(img, 0, 0, w, h);
    };

    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    setStatus("connecting");
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      attemptsLeftRef.current = RECONNECT_ATTEMPTS;
      setStatus("live");
    };
    ws.onclose = () => {
      if (attemptsLeftRef.current <= 0) {
        setStatus("closed");
        return;
      }
      attemptsLeftRef.current -= 1;
      // A renewed token arrives as a new URL and dials at once; the timer
      // redials this URL when nothing newer comes.
      onDroppedRef.current?.();
      retryTimer = setTimeout(
        () =>
          setDial((d) => (d.url === url ? { url, attempt: d.attempt + 1 } : d)),
        RECONNECT_DELAY_MS,
      );
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

    return () => {
      if (retryTimer) clearTimeout(retryTimer);
      // A frame decode in flight would otherwise draw onto a detached canvas
      // after unmount; drop the handler and abort the load.
      img.onload = null;
      img.src = "";
      ws.onopen = null;
      ws.onclose = null;
      ws.onmessage = null;
      ws.close();
      if (wsRef.current === ws) wsRef.current = null;
    };
  }, [dial]);

  const { openKeyboard } = useLiveInput({
    canvasRef,
    keyboard,
    cssSizeRef,
    send,
    enabled: interactive && !!socketUrl,
  });

  return { canvasRef, keyboardRef, openKeyboard, status, page };
}
