import { type RefObject, useCallback, useEffect } from "react";
import type {
  BrowserLiveInputMessage,
  BrowserMouseMessage,
} from "@/types/features/browserTaskTypes";

const CDP_MOUSE_BUTTONS = ["left", "middle", "right"] as const;

// The hidden keyboard input holds this one character, so whatever it gains or
// loses after an edit is exactly what the user typed or erased.
const KEYBOARD_PLACEHOLDER = " ";

// The text a non-printable key must carry for CDP to perform its action.
const KEY_ACTION_TEXT: Record<string, string | undefined> = { Enter: "\r" };

type Send = (msg: BrowserLiveInputMessage) => void;
type CssSize = RefObject<{ w: number; h: number }>;

// CDP modifier bitmask (Alt=1, Ctrl=2, Meta=4, Shift=8): without it,
// Shift-selection, capital shortcuts and Cmd/Ctrl combos silently no-op.
function toModifiers(e: MouseEvent | KeyboardEvent): number {
  return (
    (e.altKey ? 1 : 0) |
    (e.ctrlKey ? 2 : 0) |
    (e.metaKey ? 4 : 0) |
    (e.shiftKey ? 8 : 0)
  );
}

// The hidden input back to just the placeholder, the caret after it, so the
// next edit is all that changes.
function resetKeyboard(kb: HTMLInputElement): void {
  kb.value = KEYBOARD_PLACEHOLDER;
  kb.setSelectionRange(
    KEYBOARD_PLACEHOLDER.length,
    KEYBOARD_PLACEHOLDER.length,
  );
}

function pressKey(
  send: Send,
  key: string,
  keyCode: number,
  text?: string,
): void {
  const fields = {
    key,
    code: key,
    windowsVirtualKeyCode: keyCode,
    nativeVirtualKeyCode: keyCode,
  };
  send({ type: "key", event: "keyDown", ...fields, text });
  send({ type: "key", event: "keyUp", ...fields });
}

/**
 * Forwards the user's input on the live canvas as CDP-shaped messages, for
 * every surface that shows it (chat card, side panel, full-page live view).
 *
 * Pointer and keys map one to one. On a touch screen a tap arrives as the
 * emulated mouse events, a drag scrolls the page as a wheel at the point it
 * started, and the soft keyboard (raised by `openKeyboard` on the hidden input)
 * reports committed text, which goes out as one `text` message.
 */
export function useLiveInput({
  canvasRef,
  keyboard,
  cssSizeRef,
  send,
  enabled,
}: {
  canvasRef: RefObject<HTMLCanvasElement | null>;
  /** The hidden input, as an element: it mounts only once the stream is live,
   * after input is enabled, and its listeners must bind then. */
  keyboard: HTMLInputElement | null;
  cssSizeRef: CssSize;
  send: Send;
  enabled: boolean;
}) {
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!enabled || !canvas) return undefined;

    const scale = () => {
      const rect = canvas.getBoundingClientRect();
      const { w, h } = cssSizeRef.current;
      return { rect, sx: w / rect.width, sy: h / rect.height };
    };
    const toPoint = (e: { clientX: number; clientY: number }) => {
      const { rect, sx, sy } = scale();
      return {
        x: Math.round((e.clientX - rect.left) * sx),
        y: Math.round((e.clientY - rect.top) * sy),
      };
    };

    // Coalesce moves and drags to one message per animation frame: a raw
    // stream queues behind the WebSocket + CDP hop and delays the events that
    // matter (press, release).
    let pendingMove: BrowserMouseMessage | null = null;
    let pendingWheel: BrowserMouseMessage | null = null;
    let raf = 0;
    const flush = () => {
      raf = 0;
      if (pendingMove) send(pendingMove);
      if (pendingWheel) send(pendingWheel);
      pendingMove = null;
      pendingWheel = null;
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(flush);
    };

    const onMove = (e: MouseEvent) => {
      pendingMove = {
        type: "mouse",
        event: "mouseMoved",
        ...toPoint(e),
        buttons: e.buttons,
        modifiers: toModifiers(e),
      };
      schedule();
    };
    const onButton =
      (event: "mousePressed" | "mouseReleased") => (e: MouseEvent) => {
        e.preventDefault();
        if (event === "mousePressed") canvas.focus();
        flush();
        send({
          type: "mouse",
          event,
          ...toPoint(e),
          button: CDP_MOUSE_BUTTONS[e.button] ?? "left",
          buttons: e.buttons,
          clickCount: e.detail || 1,
          modifiers: toModifiers(e),
        });
      };
    const onDown = onButton("mousePressed");
    const onUp = onButton("mouseReleased");
    const onContext = (e: MouseEvent) => e.preventDefault();
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      send({
        type: "mouse",
        event: "mouseWheel",
        ...toPoint(e),
        deltaX: e.deltaX,
        deltaY: e.deltaY,
        modifiers: toModifiers(e),
      });
    };
    const onKey = (event: "keyDown" | "keyUp") => (e: KeyboardEvent) => {
      e.preventDefault();
      // CDP fires a key's default action only when `text` is set: a printable
      // char sends itself, Enter must send "\r", other keys act on their
      // virtual key code, and a Ctrl/Meta chord is not text.
      const printable = e.key.length === 1 && !e.ctrlKey && !e.metaKey;
      const text = printable ? e.key : KEY_ACTION_TEXT[e.key];
      send({
        type: "key",
        event,
        key: e.key,
        code: e.code,
        text: event === "keyDown" ? text : undefined,
        windowsVirtualKeyCode: e.keyCode,
        nativeVirtualKeyCode: e.keyCode,
        modifiers: toModifiers(e),
      });
    };
    const onKeyDown = onKey("keyDown");
    const onKeyUp = onKey("keyUp");

    let touch: {
      start: { x: number; y: number };
      x: number;
      y: number;
      moved: boolean;
    } | null = null;
    const onTouchStart = (e: TouchEvent) => {
      const t = e.touches.length === 1 ? e.touches[0] : null;
      touch = t
        ? { start: toPoint(t), x: t.clientX, y: t.clientY, moved: false }
        : null;
    };
    const onTouchMove = (e: TouchEvent) => {
      if (!touch || e.touches.length !== 1) return;
      e.preventDefault();
      const t = e.touches[0];
      const { sx, sy } = scale();
      const wheel = pendingWheel ?? {
        type: "mouse",
        event: "mouseWheel",
        ...touch.start,
        deltaX: 0,
        deltaY: 0,
      };
      wheel.deltaX = (wheel.deltaX ?? 0) + (touch.x - t.clientX) * sx;
      wheel.deltaY = (wheel.deltaY ?? 0) + (touch.y - t.clientY) * sy;
      pendingWheel = wheel;
      touch = { ...touch, x: t.clientX, y: t.clientY, moved: true };
      schedule();
    };
    const onTouchEnd = (e: TouchEvent) => {
      // A drag is not a click: cancelling its end stops the emulated mouse events.
      if (touch?.moved) e.preventDefault();
      touch = null;
    };

    const listeners: [string, EventListener, AddEventListenerOptions?][] = [
      ["mousemove", onMove as EventListener],
      ["mousedown", onDown as EventListener],
      ["mouseup", onUp as EventListener],
      ["contextmenu", onContext as EventListener],
      ["wheel", onWheel as EventListener, { passive: false }],
      ["keydown", onKeyDown as EventListener],
      ["keyup", onKeyUp as EventListener],
      ["touchstart", onTouchStart as EventListener, { passive: true }],
      ["touchmove", onTouchMove as EventListener, { passive: false }],
      ["touchend", onTouchEnd as EventListener, { passive: false }],
    ];
    for (const [type, fn, opts] of listeners)
      canvas.addEventListener(type, fn, opts);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      for (const [type, fn] of listeners) canvas.removeEventListener(type, fn);
    };
  }, [enabled, canvasRef, cssSizeRef, send]);

  useEffect(() => {
    const kb = keyboard;
    if (!enabled || !kb) return undefined;
    let composing = false;
    const read = () => {
      const typed = kb.value;
      if (typed.length < KEYBOARD_PLACEHOLDER.length) {
        pressKey(send, "Backspace", 8);
      } else if (typed.length > KEYBOARD_PLACEHOLDER.length) {
        send({ type: "text", text: typed.slice(KEYBOARD_PLACEHOLDER.length) });
      }
      resetKeyboard(kb);
    };
    const onCompositionStart = () => {
      composing = true;
    };
    // A word being composed (autocorrect, swipe typing) is read once it lands.
    const onCompositionEnd = () => {
      composing = false;
      read();
    };
    const onInput = () => {
      if (!composing) read();
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      pressKey(send, "Enter", 13, "\r");
    };
    kb.addEventListener("compositionstart", onCompositionStart);
    kb.addEventListener("compositionend", onCompositionEnd);
    kb.addEventListener("input", onInput);
    kb.addEventListener("keydown", onKeyDown);
    return () => {
      kb.removeEventListener("compositionstart", onCompositionStart);
      kb.removeEventListener("compositionend", onCompositionEnd);
      kb.removeEventListener("input", onInput);
      kb.removeEventListener("keydown", onKeyDown);
    };
  }, [enabled, keyboard, send]);

  const openKeyboard = useCallback(() => {
    if (!keyboard) return;
    resetKeyboard(keyboard);
    keyboard.focus();
  }, [keyboard]);

  return { openKeyboard };
}
