/**
 * Records what the conversation looks like at every DOM change, so a spec can
 * assert on the screen over time and not only on where it ends up.
 *
 * A MutationObserver installed before any app script runs reads the ordered
 * list of conversation items (one per `message-scroller-item`) after every
 * batch of mutations and appends it to the timeline when it changed. The
 * invariants below are the bug class the founder hit by hand: replies landing
 * above their question, messages reordering live, work splitting into two
 * sections, items vanishing, and a reload that shows something else.
 */

import { writeFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";

export interface ScreenItem {
  id: string;
  /** The server's screen item kind: user, reply, work, notice, workflow_fired, todo_woke. */
  kind: string;
  role: "user" | "bot";
  text: string;
}

export interface ScreenFrame {
  t: number;
  items: ScreenItem[];
}

declare global {
  interface Window {
    __screenTimeline?: ScreenFrame[];
  }
}

/**
 * Read the conversation the way a user sees it: every rendered screen item
 * (data-screen-item-id / data-screen-item-kind) in DOM order, skipping items
 * that render no bubble, such as an empty work item.
 */
function readScreen(): ScreenItem[] {
  return [
    ...document.querySelectorAll<HTMLElement>("[data-screen-item-id]"),
  ].flatMap((item): ScreenItem[] => {
    const user = item.querySelector<HTMLElement>(".chat_bubble_container.user");
    const bubble =
      user ?? item.querySelector<HTMLElement>(".chatbubblebot_parent");
    if (!bubble) return [];
    const kind = item.dataset.screenItemKind ?? "";
    return [
      {
        id: item.dataset.screenItemId ?? "",
        kind,
        role: kind === "user" ? "user" : "bot",
        text: bubble.innerText.trim(),
      },
    ];
  });
}

function startRecording(read: () => ScreenItem[]): void {
  const frames: ScreenFrame[] = [];
  window.__screenTimeline = frames;
  const started = performance.now();
  let last = "";
  const record = () => {
    const items = read();
    const key = JSON.stringify(items);
    if (key === last) return;
    last = key;
    frames.push({ t: Math.round(performance.now() - started), items });
  };
  const observe = () => {
    new MutationObserver(record).observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    record();
  };
  if (document.documentElement) observe();
  else document.addEventListener("DOMContentLoaded", observe, { once: true });
}

/** Record every screen change on this page, across navigations and reloads (each document starts a fresh timeline). */
export async function recordScreen(page: Page): Promise<void> {
  await page.addInitScript(
    `(${startRecording.toString()})(${readScreen.toString()})`,
  );
}

export function currentScreen(page: Page): Promise<ScreenItem[]> {
  return page.evaluate(`(${readScreen.toString()})()`) as Promise<ScreenItem[]>;
}

export function timeline(page: Page): Promise<ScreenFrame[]> {
  return page.evaluate(() => window.__screenTimeline ?? []);
}

const summarize = (items: ScreenItem[]): string =>
  items
    .map((i) => `${i.role}:${i.text.split("\n")[0].slice(0, 40)}`)
    .join(" | ");

/**
 * Every violation of "the screen only grows": an item changing position
 * relative to another, an item vanishing, or one id shown twice.
 */
export function timelineViolations(frames: ScreenFrame[]): string[] {
  const problems: string[] = [];
  frames.forEach((frame, index) => {
    const ids = frame.items.map((i) => i.id);
    const dupes = ids.filter((id, i) => ids.indexOf(id) !== i);
    if (dupes.length > 0) {
      problems.push(
        `t=${frame.t} duplicate items ${dupes.join(",")}: ${summarize(frame.items)}`,
      );
    }
    if (index === 0) return;
    const before = frames[index - 1];
    const now = new Set(ids);
    const gone = before.items.filter((i) => !now.has(i.id));
    if (gone.length > 0) {
      problems.push(
        `t=${frame.t} vanished ${summarize(gone)}\n  before: ${summarize(before.items)}\n  after:  ${summarize(frame.items)}`,
      );
    }
    const kept = before.items.map((i) => i.id).filter((id) => now.has(id));
    const keptNow = ids.filter((id) => kept.includes(id));
    if (kept.join() !== keptNow.join()) {
      problems.push(
        `t=${frame.t} reordered\n  before: ${summarize(before.items)}\n  after:  ${summarize(frame.items)}`,
      );
    }
  });
  return problems;
}

/** Assert the page's timeline so far never reordered, dropped or duplicated an item. */
export async function expectScreenOnlyGrew(page: Page): Promise<ScreenFrame[]> {
  const frames = await timeline(page);
  const path = test.info().outputPath(`screen-timeline-${Date.now()}.json`);
  writeFileSync(path, JSON.stringify(frames, null, 1));
  await test
    .info()
    .attach("screen timeline", { path, contentType: "application/json" });
  expect(frames.length, "the recorder saw the conversation").toBeGreaterThan(0);
  expect(timelineViolations(frames)).toEqual([]);
  return frames;
}

/** Lines across bot items that read exactly `text`: a tool card's title or a reply. */
export function botLinesReading(items: ScreenItem[], text: string): number {
  return items
    .filter((i) => i.role === "bot")
    .flatMap((i) => i.text.split("\n"))
    .filter((line) => line.trim() === text).length;
}

/** "Used N tools" headers on screen: one per piece of work, never two for one work. */
export function toolSections(items: ScreenItem[]): number {
  return items
    .filter((i) => i.role === "bot")
    .flatMap((i) => i.text.split("\n"))
    .filter((line) => /^Used \d+ tools?$/.test(line.trim())).length;
}

/**
 * Wait until a bot line reads `lastLine`, no loading row is shown, and the
 * screen stops changing; returns it.
 */
export async function settledScreen(
  page: Page,
  lastLine: string,
  timeoutMs: number,
): Promise<ScreenItem[]> {
  await expect
    .poll(async () => botLinesReading(await currentScreen(page), lastLine), {
      timeout: timeoutMs,
    })
    .toBeGreaterThan(0);
  await expect(page.getByTestId("chat-loading-row")).toHaveCount(0, {
    timeout: timeoutMs,
  });
  let previous = JSON.stringify(await currentScreen(page));
  await expect
    .poll(
      async () => {
        const now = JSON.stringify(await currentScreen(page));
        const same = now === previous;
        previous = now;
        return same;
      },
      { timeout: timeoutMs, intervals: [3_000] },
    )
    .toBe(true);
  return currentScreen(page);
}

/**
 * The live screen, then the same conversation reloaded: they must match item
 * for item, and the reload's own timeline must only grow too.
 */
export async function expectReloadMatches(
  page: Page,
  live: ScreenItem[],
  timeoutMs: number,
): Promise<void> {
  await page.reload();
  await expect
    .poll(async () => currentScreen(page), { timeout: timeoutMs })
    .toEqual(live);
  await expectScreenOnlyGrew(page);
}
