import { EventEmitter } from "node:events";
import { render } from "ink";
import type { ReactElement } from "react";

/** A terminal Ink can draw to: it records every write, and the test may resize it. */
export function fakeTerminal(columns: number, rows: number) {
  let written = "";
  const stream = Object.assign(new EventEmitter(), {
    columns,
    rows,
    isTTY: true,
    write: (chunk: string) => {
      written += chunk;
      return true;
    },
  });
  return { stream, written: (): string => written };
}

/** Render to a fake terminal of this size. */
export function renderOn(
  element: ReactElement,
  columns: number,
  rows: number,
  options: { debug?: boolean } = {},
) {
  const terminal = fakeTerminal(columns, rows);
  const app = render(element, {
    stdout: terminal.stream as unknown as NodeJS.WriteStream,
    patchConsole: false,
    debug: options.debug,
  });
  return { ...terminal, app };
}

/** Let React commit and Ink draw. */
export const tick = (): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, 20));
