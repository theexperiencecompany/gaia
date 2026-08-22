"use client";

import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

/** One palette activation of an item: what was picked and when. */
export interface FrecencyEntry {
  id: string;
  ts: number;
}

interface FrecencyStore {
  entries: FrecencyEntry[];
  record: (id: string) => void;
}

/** Ring-buffer cap — old activations fall off the back. */
const MAX_ENTRIES = 200;
/** Half-life of a single activation's influence, in hours. */
const HALF_LIFE_H = 72;

/**
 * What the user picks in the palette is the strongest relevance signal we
 * have. Append-only log of activations (persisted), decayed to boost future
 * rankings; cold start falls back to data timestamps.
 */
export const useFrecencyStore = create<FrecencyStore>()(
  devtools(
    persist(
      (set) => ({
        entries: [],
        record: (id) =>
          set(
            (state) => ({
              entries: [
                ...state.entries.slice(-(MAX_ENTRIES - 1)),
                { id, ts: Date.now() },
              ],
            }),
            false,
            "commandFrecency/record",
          ),
      }),
      {
        name: "command-frecency-storage",
        partialize: (state) => ({ entries: state.entries }),
      },
    ),
    { name: "command-frecency-store" },
  ),
);

/**
 * Decay-weighted pick count for one item id, capped so a single hot item
 * can't dominate. Returns roughly 0–10.
 */
export function frecencyScore(entries: FrecencyEntry[], id: string): number {
  const now = Date.now();
  let score = 0;
  // Newest first: only the most recent occurrences count.
  let counted = 0;
  for (let i = entries.length - 1; i >= 0 && counted < 10; i--) {
    const entry = entries[i];
    if (entry.id !== id) continue;
    const ageHours = Math.max(0, (now - entry.ts) / 3_600_000);
    score += 0.5 ** (ageHours / HALF_LIFE_H);
    counted++;
  }
  return score;
}
