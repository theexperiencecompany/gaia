// @vitest-environment jsdom
/**
 * The phone keyboard's hidden input appears only once the stream is live,
 * after input forwarding is already on. Its typing must still reach the page:
 * bound once at enable time, the listener found no input and every keystroke
 * typed on a phone was silently dropped.
 */
import { fireEvent, render } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { useLiveInput } from "@/features/browser/hooks/useLiveInput";
import type { BrowserLiveInputMessage } from "@/types/features/browserTaskTypes";

function Harness({
  send,
  showKeyboard,
}: {
  send: (msg: BrowserLiveInputMessage) => void;
  showKeyboard: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const cssSizeRef = useRef({ w: 1280, h: 800 });
  const [keyboard, setKeyboard] = useState<HTMLInputElement | null>(null);
  useLiveInput({
    canvasRef,
    keyboard,
    cssSizeRef,
    send,
    enabled: true,
  });
  return (
    <>
      <canvas ref={canvasRef} />
      {showKeyboard && <input aria-label="kb" ref={setKeyboard} />}
    </>
  );
}

describe("useLiveInput", () => {
  it("forwards text typed into a keyboard input that mounts after input was enabled", () => {
    const send = vi.fn();
    const view = render(<Harness send={send} showKeyboard={false} />);
    view.rerender(<Harness send={send} showKeyboard />);

    const kb = view.getByLabelText("kb") as HTMLInputElement;
    fireEvent.input(kb, { target: { value: " a" } });

    expect(send).toHaveBeenCalledWith({ type: "text", text: "a" });
  });
});
