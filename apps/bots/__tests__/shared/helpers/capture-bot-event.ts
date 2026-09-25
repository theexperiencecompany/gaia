/** Captures the `bot_event` lines a bot boundary really prints, parsed. */
import { vi } from "vitest";

const CONSOLE_LEVELS = ["log", "warn", "error", "debug"] as const;

/** Runs `body`, returning every `bot_event` printed meanwhile, for `task`. */
export async function captureBotEvents(
  task: string,
  body: () => Promise<unknown>,
): Promise<Record<string, unknown>[]> {
  const lines: string[] = [];
  const spies = CONSOLE_LEVELS.map((level) =>
    vi.spyOn(console, level).mockImplementation((line: unknown) => {
      if (typeof line === "string") lines.push(line);
    }),
  );
  try {
    await body();
  } finally {
    for (const spy of spies) spy.mockRestore();
  }
  return lines
    .map((line) => {
      try {
        return JSON.parse(line) as Record<string, unknown>;
      } catch {
        return undefined;
      }
    })
    .filter(
      (event): event is Record<string, unknown> =>
        event?.message === "bot_event" && event.task === task,
    );
}
