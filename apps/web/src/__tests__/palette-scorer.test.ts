/**
 * Unit tests for the palette's relevance scorer (features/command/model/scorer.ts).
 *
 * The scorer decides which row wins the palette, so the tiers it promises in
 * its docs are load-bearing: exact > prefix > word-boundary > substring >
 * subsequence. These tests pin each tier, the bonuses inside the subsequence
 * tier, and the multi-term / multi-field contract.
 */
import { describe, expect, it } from "vitest";

import { scoreFields, scoreTerm } from "@/features/command/model/scorer";

describe("scoreTerm — match tiers", () => {
  it("ranks exact above prefix above word-boundary above plain substring", () => {
    const exact = scoreTerm("workflows", "workflows");
    const prefix = scoreTerm("work", "workflows page");
    // "work" sits right after a space — a true word boundary.
    const boundary = scoreTerm("work", "git workflows page");
    const substring = scoreTerm("orkflow", "wworkflows page");
    expect(exact).toBeGreaterThan(prefix);
    expect(prefix).toBeGreaterThan(boundary);
    expect(boundary).toBeGreaterThan(substring);
  });

  it("scores camelCase transitions as word boundaries", () => {
    // "clock" sits at a camelCase boundary inside "AlarmClockIcon".
    const camelBoundary = scoreTerm("clock", "alarmClockIcon");
    const midWord = scoreTerm("lock", "alarmClockIcon".toLowerCase());
    expect(camelBoundary).toBeGreaterThanOrEqual(80);
    expect(camelBoundary).toBeGreaterThan(midWord);
  });

  it("returns 0 when nothing matches", () => {
    expect(scoreTerm("xyz", "workflows")).toBe(0);
    expect(scoreTerm("", "workflows")).toBe(0);
    expect(scoreTerm("work", "")).toBe(0);
  });
});

describe("scoreTerm — subsequence matching", () => {
  it("matches out-of-order characters with a low score", () => {
    const score = scoreTerm("wfl", "workflows");
    expect(score).toBeGreaterThan(0);
    expect(score).toBeLessThanOrEqual(40);
  });

  it("rewards consecutive runs over spread-out matches", () => {
    // "de" is consecutive in "index deploy"; split across "deploy index" too,
    // but consecutive runs must outrank the scattered variant.
    const consecutive = scoreTerm("dep", "index deploy tool");
    const scattered = scoreTerm("dpl", "index deploy tool");
    expect(consecutive).toBeGreaterThan(0);
    expect(scattered).toBeGreaterThan(0);
    expect(consecutive).toBeGreaterThan(scattered);
  });

  it("never lets a subsequence outrank a real substring hit", () => {
    const substring = scoreTerm("run", "run now");
    const subseq = scoreTerm("rn", "runner");
    expect(substring).toBeGreaterThan(subseq);
  });
});

describe("scoreFields — multi-term and weighting", () => {
  it("requires every whitespace-separated term to match", () => {
    const both = scoreFields("new chat", [{ text: "start a new chat" }]);
    const half = scoreFields("new zebra", [{ text: "start a new chat" }]);
    expect(both).toBeGreaterThan(0);
    expect(half).toBe(0);
  });

  it("weights fields so title hits outrank keyword hits", () => {
    const query = "spotify";
    const titleHit = scoreFields(query, [
      { text: "Spotify", weight: 2 },
      { text: "music app" },
    ]);
    const keywordHit = scoreFields(query, [
      { text: "something else entirely" },
      { text: "connect spotify music", weight: 1 },
    ]);
    expect(titleHit).toBeGreaterThan(keywordHit);
  });

  it("matches terms scattered across fields (title + keywords), at averaged strength", () => {
    // "new" lives in the title, "compose" only in keywords — the row must
    // still surface, but below a single-field exact match.
    const scattered = scoreFields("new compose", [
      { text: "New chat", weight: 2 },
      { text: "compose message", weight: 1 },
    ]);
    expect(scattered).toBeGreaterThan(0);

    const singleFieldExact = scoreFields("new chat", [
      { text: "New chat", weight: 2 },
      { text: "compose message", weight: 1 },
    ]);
    // Both words are word-boundary prefix hits inside the title:
    // (90 + 80) / 2 * weight 2
    expect(singleFieldExact).toBe(170);
    expect(scattered).toBeLessThan(singleFieldExact);
  });

  it("still zeroes when a term exists nowhere across fields", () => {
    expect(
      scoreFields("new zebra", [
        { text: "New chat", weight: 2 },
        { text: "compose message" },
      ]),
    ).toBe(0);
  });

  it("averages per-term scores so extra terms don't inflate a field past an exact single-term match", () => {
    const singleExact = scoreFields("chat", [{ text: "chat", weight: 2 }]);
    const twoTerms = scoreFields("chat now", [
      { text: "chat now please", weight: 2 },
    ]);
    expect(singleExact).toBe(200);
    expect(twoTerms).toBeLessThan(singleExact);
  });

  it("returns 0 for an empty/whitespace query", () => {
    expect(scoreFields("", [{ text: "anything" }])).toBe(0);
    expect(scoreFields("   ", [{ text: "anything" }])).toBe(0);
  });

  it("ignores undefined fields instead of failing", () => {
    expect(
      scoreFields("todo", [
        { text: undefined, weight: 2 },
        { text: "create todo" },
      ]),
    ).toBeGreaterThan(0);
  });
});
