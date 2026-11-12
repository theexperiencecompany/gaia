// @vitest-environment jsdom
/**
 * Brief items: the owner's copy opens the in-app todo even when the brief also
 * shared a public link; the public copy (no todo_id) opens the shared link.
 * The written message links an item on its phrase, never as a pasted URL.
 * What the composition left out is listed after it, so the page loses nothing,
 * and so is every composed block the day's edition could not draw.
 */

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
    kicker: "THE MORNING BRIEF",
    date: "2026-10-14",
    headline: "Your morning",
    lede: "",
    stats: [],
    sections: [{ numeral: "I", title: "GAIA'S WORK", items: [item] }],
    mood: "packed",
    caption: "",
    hue: 10,
  };
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

  it("lists what the composition left out under Everything else, each opening its source", () => {
    render(
      <BriefingEdition
        payload={{
          ...payload({ text: "Deck", kind: "lookback" }),
          uncomposed: [
            {
              title: "Fix the login redirect",
              detail: "due tomorrow",
              kind: "you",
              app: "Linear",
              url: "https://linear.app/ENG-12",
              todo_id: null,
            },
            {
              title: "Digest: three papers",
              detail: null,
              kind: "note",
              app: "GAIA",
              url: null,
              todo_id: "t9",
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("Everything else")).toBeTruthy();
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

  it("shows no Everything else group when the composition placed everything", () => {
    render(
      <BriefingEdition payload={payload({ text: "Deck", kind: "lookback" })} />,
    );

    expect(screen.queryByText("Everything else")).toBeNull();
  });

  it("lists under the edition only what it could not draw or left out", () => {
    render(
      <BriefingEdition
        imageUrl="https://cdn.example/edition.png"
        payload={{
          ...payload({ text: "Deck", kind: "lookback" }),
          message: "The deck is ready.",
          undrawn: [{ kind: "note", text: "Three hires closed this week." }],
          uncomposed: [
            {
              title: "Fix the login redirect",
              detail: "due tomorrow",
              kind: "you",
              app: "Linear",
              url: "https://linear.app/ENG-12",
              todo_id: null,
            },
          ],
        }}
      />,
    );

    expect(screen.getByRole("img", { name: "Your morning" })).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "More from GAIA" }),
    ).toBeTruthy();
    expect(screen.getByText("Three hires closed this week.")).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Everything else" }),
    ).toBeTruthy();
    expect(screen.queryByText("Your morning")).toBeNull();
    expect(screen.queryByText("The deck is ready.")).toBeNull();
    expect(screen.queryByText("Deck")).toBeNull();
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
                origin: "memory",
                done: 5,
                open: 3,
                linked: [],
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

  it("lists the items the edition's three rows cut off, the weekly lead it could not draw and the events past three", () => {
    const item = (text: string) => ({ text, kind: "you" as const });
    render(
      <BriefingEdition
        imageUrl="https://cdn.example/edition.png"
        payload={{
          ...payload(item("unused")),
          sections: [
            {
              numeral: "I",
              title: "Lead",
              items: [item("Weekly lead request")],
            },
            {
              numeral: "II",
              title: "Needs you",
              items: ["One", "Two", "Three", "Fourth row", "Fifth row"].map(
                item,
              ),
            },
          ],
          blocks: [{ kind: "items", section: 1 }],
          undrawn: [{ kind: "lead", section: 0 }],
          calendar: ["A", "B", "C", "Late call"].map((title, at) => ({
            date: "2026-10-14",
            title,
            start: `0${at + 8}:00`,
          })),
        }}
      />,
    );

    expect(screen.getByText("Weekly lead request")).toBeTruthy();
    expect(screen.getByText("Fourth row")).toBeTruthy();
    expect(screen.getByText("Fifth row")).toBeTruthy();
    expect(screen.getByText(/Late call/)).toBeTruthy();
    expect(screen.queryByText("Three")).toBeNull();
    expect(screen.queryByText("B")).toBeNull();
  });
});
