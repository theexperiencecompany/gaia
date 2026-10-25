import { useStdout } from "ink";
import { useEffect, useState } from "react";
import { type TerminalSize, terminalSize } from "../../lib/terminal-text.js";

/**
 * The terminal's size, re-rendering on resize: Ink re-lays-out the last frame
 * then, but never re-renders, so a width read during render goes stale.
 */
export function useTerminalSize(): TerminalSize {
  const { stdout } = useStdout();
  const [size, setSize] = useState(() => terminalSize(stdout));

  useEffect(() => {
    const onResize = (): void => setSize(terminalSize(stdout));
    stdout.on("resize", onResize);
    return () => {
      stdout.off("resize", onResize);
    };
  }, [stdout]);

  return size;
}
