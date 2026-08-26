/**
 * Unit tests for the palette frecency store (features/command/frecency.ts).
 *
 * The store persists what the user picks so future rankings can boost it.
 * These pin the ring-buffer cap, decay ordering (recent > old), and the
 * score bounds that paletteModel's boost relies on. localStorage doesn't
 * exist in the node test environment — zustand's persist middleware skips
 * persistence when storage is unavailable, which is exactly the behavior
 * under test here (in-memory state must still work).
 */
import { beforeEach, describe, expect, it } from "vitest";

import { frecencyScore, useFrecencyStore } from "@/features/command/frecency";

const record = (id: string) => useFrecencyStore.getState().record(id);

beforeEach(() => {
  useFrecencyStore.setState({ entries: [] });
});

describe("record", () => {
  it("appends activations with a timestamp", () => {
    record("chat:1");
    const { entries } = useFrecencyStore.getState();
    expect(entries).toHaveLength(1);
    expect(entries[0].id).toBe("chat:1");
    expect(entries[0].ts).toBeLessThanOrEqual(Date.now());
  });

  it("caps the ring buffer at 200 entries", () => {
    for (let i = 0; i < 210; i++) record(`item:${i}`);
    const { entries } = useFrecencyStore.getState();
    expect(entries).toHaveLength(200);
    // Oldest fell off the front; newest is intact.
    expect(entries[0].id).toBe("item:10");
    expect(entries[199].id).toBe("item:209");
  });
});

describe("frecencyScore", () => {
  it("returns 0 for items never picked", () => {
    record("chat:1");
    expect(frecencyScore(useFrecencyStore.getState().entries, "chat:2")).toBe(
      0,
    );
  });

  it("scores recent picks higher than old ones", () => {
    const now = Date.now();
    const hourAgo = now - 60 * 60 * 1000;
    const weekAgo = now - 7 * 24 * 60 * 60 * 1000;
    const entries = [
      { id: "old", ts: weekAgo },
      { id: "fresh", ts: hourAgo },
    ];
    expect(frecencyScore(entries, "fresh")).toBeGreaterThan(
      frecencyScore(entries, "old"),
    );
  });

  it("grows with repeated picks", () => {
    const entries = [
      { id: "hot", ts: Date.now() },
      { id: "hot", ts: Date.now() },
      { id: "hot", ts: Date.now() },
    ];
    const once = [{ id: "hot", ts: Date.now() }];
    expect(frecencyScore(entries, "hot")).toBeGreaterThan(
      frecencyScore(once, "hot"),
    );
  });

  it("counts at most the 10 most recent occurrences per item", () => {
    const now = Date.now();
    // Store reality: later records sit at higher indices. Build the fixture
    // the same way — newest LAST.
    const fifteen = Array.from({ length: 15 }, (_, i) => ({
      id: "spam",
      ts: now - (15 - i) * 1000,
    }));
    const ten = fifteen.slice(5);
    expect(frecencyScore(fifteen, "spam")).toBeCloseTo(
      frecencyScore(ten, "spam"),
      6,
    );
  });

  it("stays bounded so boosts can't outrank exact title matches", () => {
    const now = Date.now();
    const entries = Array.from({ length: 10 }, (_, i) => ({
      id: "hot",
      // Ten same-hour picks: each contributes ~1.
      ts: now - i * 60_000,
    }));
    // paletteModel multiplies by 3 and caps at 200; an exact title match
    // scores 200 on its own, so even max frecency must stay below that
    // after the multiplier.
    expect(frecencyScore(entries, "hot") * 3).toBeLessThan(200);
  });
});
