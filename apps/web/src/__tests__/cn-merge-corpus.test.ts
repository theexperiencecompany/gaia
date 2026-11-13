import { describe, expect, it } from "vitest";
import { cn } from "@/lib/utils";
import corpus from "./fixtures/cn-merge-corpus.json";

type MergeCase = readonly [args: readonly string[], expected: string];

function parseCase(entry: ReadonlyArray<string | string[]>): MergeCase {
  const [args, expected] = entry;
  if (!Array.isArray(args) || typeof expected !== "string") {
    throw new Error(`malformed corpus entry: ${JSON.stringify(entry)}`);
  }
  return [args, expected];
}

/**
 * Real class strings from this repo whose merge drops or reorders a class,
 * with the output the previous engine (the cn package) produced. cn now comes
 * from tailwind-variants; any case that merges differently fails here.
 */
const CASES = corpus.map(parseCase);

describe("cn merges the repo's class strings exactly as before", () => {
  it.each(CASES.map(([args, expected]) => [args.join(" + "), args, expected]))(
    "%s",
    (_label, args, expected) => {
      expect(cn(...args)).toBe(expected);
    },
  );
});
