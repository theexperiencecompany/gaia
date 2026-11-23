// @vitest-environment jsdom
/**
 * Brief items: the owner's copy opens the in-app todo even when the brief also
 * shared a public link; the public copy (no todo_id) opens the shared link.
 * The written message links an item on its phrase, never as a pasted URL.
 * What the API says the edition left out is listed after it, so the page loses
 * nothing, and so is every composed block the day's edition could not draw.
 */

import type {
  BriefingItem,
  EditionLeftOut,
  UncomposedItem,
} from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BriefingEdition,
  type BriefingEditionPayload,
} from "@/features/briefing/components/BriefingEdition";

const PUBLIC_LINK = "https://heygaia.link/abcdefghijk";

function payload(
  item: BriefingEditionPayload["sections"][number]["items"][number],
): BriefingEditionPayload {
  return {
    headline: "Your morning",
    sections: [{ numeral: "I", title: "GAIA'S WORK", items: [item] }],
  };
}

function leftOut(parts: Partial<EditionLeftOut>): EditionLeftOut {
  return { items: [], events: [], uncomposed: [], ...parts };
}

function leftOutItem(text: string): BriefingItem {
  return {
    text,
    kind: "you",
    action: "reply",
    outcome: null,
    detail: null,
    todo_id: null,
    link: null,
    count: 1,
    app: null,
    source: null,
    url: null,
    people: [],
    offer: null,
  };
}

const LOGIN_FIX: UncomposedItem = {
  title: "Fix the login redirect",
  detail: "due tomorrow",
  kind: "you",
  state_label: "Waiting on you",
  app: "Linear",
  url: "https://linear.app/ENG-12",
  todo_id: null,
};

/** The matches a sighted reader sees; the edition's screen-reader copy of the letter is left out. */
function shown(text: string | RegExp): HTMLElement[] {
  return screen
    .queryAllByText(text)
    .filter((element) => !element.closest(".sr-only"));
}

describe("brief item links", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the owner to the in-app todo, not the public page", () => {
    render(
      <BriefingEdition
        payload={payload({
          text: "Deck",
          todo_id: "t1",
          link: PUBLIC_LINK,
          kind: "lookback",
        })}
      />,
    );

    expect(
      screen.getByRole("link", { name: "Deck" }).getAttribute("href"),
    ).toBe("/todos?todoId=t1");
  });

  it("sends a public reader to the link the brief shared", () => {
    render(
      <BriefingEdition
        payload={payload({ text: "Deck", link: PUBLIC_LINK, kind: "lookback" })}
      />,
    );

    expect(
      screen.getByRole("link", { name: "Deck" }).getAttribute("href"),
    ).toBe(PUBLIC_LINK);
  });

  it("renders an unlinked public item as plain text", () => {
    render(
      <BriefingEdition payload={payload({ text: "Deck", kind: "lookback" })} />,
    );

    expect(screen.queryByRole("link")).toBeNull();
  });

  it("makes the message's linked phrase tappable instead of printing its markup", () => {
    // A link's preview loads once in view (jsdom has no IntersectionObserver)
    // through the app-wide query client.
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe = vi.fn();
        unobserve = vi.fn();
        disconnect = vi.fn();
        takeRecords = vi.fn(() => []);
      },
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <BriefingEdition
          payload={{
            ...payload({ text: "Deck", kind: "lookback" }),
            message: `The [venue shortlist](${PUBLIC_LINK}) is ready.`,
          }}
        />
      </QueryClientProvider>,
    );

    expect(
      screen
        .getByRole("link", { name: "venue shortlist" })
        .getAttribute("href"),
    ).toBe(PUBLIC_LINK);
    expect(screen.queryByText(/\]\(/)).toBeNull();
  });

  it("lists what the composition left out as also on your radar, each with its source and the API's words for its state", () => {
    render(
      <BriefingEdition
        payload={payload({ text: "Deck", kind: "lookback" })}
        leftOut={leftOut({
          uncomposed: [
            LOGIN_FIX,
            {
              title: "Digest: three papers",
              detail: null,
              kind: "note",
              state_label: "Note",
              app: "GAIA",
              url: null,
              todo_id: "t9",
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("Also on your radar")).toBeTruthy();
    for (const context of [
      "Linear",
      "Waiting on you",
      "due tomorrow",
      "Note",
    ]) {
      expect(screen.getByText(context)).toBeTruthy();
    }
    expect(
      screen
        .getByRole("link", { name: "Fix the login redirect" })
        .getAttribute("href"),
    ).toBe("https://linear.app/ENG-12");
    expect(
      screen
        .getByRole("link", { name: "Digest: three papers" })
        .getAttribute("href"),
    ).toBe("/todos?todoId=t9");
  });

  it("shows no radar aside when the composition placed everything", () => {
    render(
      <BriefingEdition payload={payload({ text: "Deck", kind: "lookback" })} />,
    );

    expect(screen.queryByText("Also on your radar")).toBeNull();
  });

  it("lists under the edition only what it could not draw or left out", () => {
    render(
      <BriefingEdition
        imageUrl="https://cdn.example/edition.png"
        payload={{
          ...payload({ text: "Deck", kind: "lookback" }),
          message: "The deck is ready.",
          undrawn: [{ kind: "note", text: "Three hires closed this week." }],
        }}
        leftOut={leftOut({ uncomposed: [LOGIN_FIX] })}
      />,
    );

    expect(screen.getByRole("img", { name: "Your morning" })).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "More from GAIA" }),
    ).toBeTruthy();
    expect(shown("Three hires closed this week.")).toHaveLength(1);
    expect(
      screen.getByRole("heading", { name: "Also on your radar" }),
    ).toBeTruthy();
    expect(
      screen.getByText("Other things GAIA found that didn't make the brief."),
    ).toBeTruthy();
    expect(screen.getByText("Linear")).toBeTruthy();
    expect(shown("Your morning")).toHaveLength(0);
    expect(shown("The deck is ready.")).toHaveLength(0);
    expect(shown("Deck")).toHaveLength(0);
  });

  it("says every block the edition could not draw, and nothing for the rest", () => {
    render(
      <BriefingEdition
        payload={{
          ...payload({ text: "Deck", kind: "lookback" }),
          undrawn: [
            {
              kind: "chart",
              chart: "line",
              title: "Emails received each day",
              takeaway: "Yesterday brought 61.",
              series: [],
            },
            {
              kind: "progress",
              goal: {
                id: "g1",
                statement: "Fill eight roles",
                done: 5,
                done_by_gaia: 3,
                done_by_you: 2,
                open: 3,
                linked: [],
                stalled: [],
                since: null,
              },
            },
            { kind: "lead", section: 0 },
          ],
        }}
      />,
    );

    expect(screen.getByText("More from GAIA")).toBeTruthy();
    expect(
      screen.getByText("Emails received each day: Yesterday brought 61."),
    ).toBeTruthy();
    expect(screen.getByText("Fill eight roles: 5 of 8 done")).toBeTruthy();
  });

  it("lists under the edition the items and events the API says it left out", () => {
    render(
      <BriefingEdition
        imageUrl="https://cdn.example/edition.png"
        payload={payload({ text: "Drawn row", kind: "you" })}
        leftOut={leftOut({
          items: [
            leftOutItem("Weekly lead request"),
            leftOutItem("Fourth row"),
          ],
          events: [{ date: "2026-10-14", start: "11:00", title: "Late call" }],
        })}
      />,
    );

    expect(shown("Weekly lead request")).toHaveLength(1);
    expect(shown("Fourth row")).toHaveLength(1);
    expect(shown(/Late call/)).toHaveLength(1);
    expect(shown("Drawn row")).toHaveLength(0);
  });
});
