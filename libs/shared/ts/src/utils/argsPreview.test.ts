import { describe, expect, it } from "vitest";
import { flattenArgsPreview } from "./argsPreview";

const calendarArgs = {
  events: [
    {
      calendar_id: "primary",
      summary: "Team standup",
      description: "Daily sync",
      start_datetime: "2026-09-21T10:00:00",
      end_datetime: "2026-09-21T10:30:00",
      location: "Meet",
      attendees: ["a@x.com", "b@x.com"],
      is_all_day: false,
      create_meeting_room: false,
    },
    {
      calendar_id: "primary",
      summary: "1:1 with Priya",
      description: null,
      start_datetime: "2026-09-21T14:00:00",
      end_datetime: "2026-09-21T15:00:00",
      location: "",
      attendees: [],
      is_all_day: false,
    },
  ],
};

describe("flattenArgsPreview", () => {
  it("shows nested event content instead of one top-level scalar", () => {
    const { rows, omitted } = flattenArgsPreview(calendarArgs);
    const keys = rows.map((row) => `${row.group ?? ""}:${row.key}`);
    expect(keys).toContain("Event 1:summary");
    expect(keys).toContain("Event 1:start datetime");
    expect(keys).toContain("Event 1:attendees");
    expect(keys).toContain("Event 2:summary");
    // Null description, empty location/attendees of event 2 are skipped.
    expect(keys).not.toContain("Event 2:description");
    expect(keys).not.toContain("Event 2:location");
    expect(omitted).toBe(0);
  });

  it("humanizes datetimes, booleans and lists", () => {
    const { rows } = flattenArgsPreview(calendarArgs);
    const byKey = new Map(
      rows.map((row) => [`${row.group ?? ""}:${row.key}`, row.value]),
    );
    expect(byKey.get("Event 1:start datetime")).toBe("Mon, Sep 21, 10:00 AM");
    expect(byKey.get("Event 1:attendees")).toBe("a@x.com, b@x.com");
    expect(byKey.get("Event 1:is all day")).toBe("No");
  });

  it("keeps top-level scalars", () => {
    const { rows } = flattenArgsPreview({
      to: "a@example.com",
      count: 3,
      urgent: true,
    });
    expect(rows).toEqual([
      { key: "to", value: "a@example.com", group: null },
      { key: "count", value: "3", group: null },
      { key: "urgent", value: "Yes", group: null },
    ]);
  });

  it("walks one level into objects instead of dropping them", () => {
    const { rows } = flattenArgsPreview({
      event: { title: "Standup", location: "Zoom" },
    });
    expect(rows).toEqual([
      { key: "event title", value: "Standup", group: null },
      { key: "event location", value: "Zoom", group: null },
    ]);
  });

  it("never crashes on hostile shapes", () => {
    expect(flattenArgsPreview({}).rows).toEqual([]);
    expect(
      flattenArgsPreview({ a: null, b: undefined, c: "", d: [] }).rows,
    ).toEqual([]);
    expect(
      flattenArgsPreview({ deep: { deeper: { deepest: { x: 1 } } } }).omitted,
    ).toBe(1);
  });

  it("caps array items and rows, counting what it drops", () => {
    const many = flattenArgsPreview({
      events: Array.from({ length: 10 }, (_, i) => ({ summary: `E${i}` })),
    });
    expect(many.rows).toHaveLength(4);
    expect(many.omitted).toBe(6);

    const big: Record<string, unknown> = {};
    for (let i = 0; i < 50; i++) big[`field_${i}`] = `value ${i}`;
    const capped = flattenArgsPreview(big);
    expect(capped.rows).toHaveLength(20);
    expect(capped.omitted).toBe(30);
  });
});
