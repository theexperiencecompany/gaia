import { createParser } from "@openuidev/react-lang";
import { describe, expect, it } from "vitest";
import {
  buildIndex,
  extractProgram,
  resolveText,
  sourceNumbers,
  ungrounded,
} from "./grounding";
import { artifactSpecLibrary } from "./specLibrary";

// The launch dashboard's funnel: a figure in prose must come from this data, rendered by code.
const SOURCE =
  "Funnel: signed up 1,840; connected a calendar 1,210; made a first plan 754; saw the paywall 612; paid 96.";
const FUNNEL =
  'funnel1 = Funnel("The paywall step loses the most people", "Week-one cohort", [["Signed up", 1840], ["Connected a calendar", 1210], ["Made a first plan", 754], ["Saw the paywall", 612], ["Paid", 96]])';

const parser = createParser(artifactSpecLibrary.toJSONSchema(), "Artifact");

function indexOf(program: string) {
  return buildIndex(parser.parse(program).root);
}

function calloutText(text: string): { text: string; unknown: string[] } {
  const program = `root = Artifact("Atlas launch", "Week one", [], [funnel1])\n${FUNNEL}\n`;
  return resolveText(text, indexOf(program));
}

describe("grounded figures", () => {
  it("flags a typed number the source never states", () => {
    const typed = "142 people who made a first plan did not see the paywall.";
    expect(ungrounded(typed, sourceNumbers(SOURCE))).toEqual(["142"]);
  });

  it("fills the largest absolute drop from the funnel: 630, not the paywall's 516", () => {
    const r = calloutText(
      "{funnel1.maxDrop} people dropped at {funnel1.maxDropStage}.",
    );
    expect(r.unknown).toEqual([]);
    expect(r.text).toBe(
      "630 people dropped at Signed up to Connected a calendar.",
    );
  });

  it("gives the largest relative loss its own slot", () => {
    const r = calloutText(
      "{funnel1.worstStep} loses {funnel1.worstStepLoss} of people.",
    );
    expect(r.text).toBe("Saw the paywall to Paid loses 84.3% of people.");
  });

  it("leaves a slot of a one-stage funnel visible instead of crashing on it", () => {
    const program = `root = Artifact("Atlas launch", "Week one", [], [funnel1])\nfunnel1 = Funnel("One step", "Week one", [["Signed up", 1840]])\n`;
    const r = resolveText("{funnel1.first} signed up.", indexOf(program));
    expect(r.unknown).toEqual(["funnel1.first"]);
    expect(r.text).toBe("{funnel1.first} signed up.");
  });

  it("lists an unknown slot and leaves it visible", () => {
    const r = calloutText("{funnel1.maxDrops} people dropped.");
    expect(r.unknown).toEqual(["funnel1.maxDrops"]);
    expect(r.text).toBe("{funnel1.maxDrops} people dropped.");
  });

  it("grounds each number in an unspaced source list", () => {
    const source = sourceNumbers(`${SOURCE} Product Hunt per day: 190,160,70.`);
    expect(
      ungrounded("Product Hunt brought 160 sign-ups on Wednesday.", source),
    ).toEqual([]);
  });

  it("grounds an integer inside a stated range", () => {
    const source = sourceNumbers(`${SOURCE} Plans by hour (6..21).`);
    expect(ungrounded("Few plans are made at 13h.", source)).toEqual([]);
    expect(ungrounded("Few plans are made at 23h.", source)).toEqual(["23"]);
  });

  it("rounds an approximate figure through a ~ slot", () => {
    const r = calloutText("About {funnel1.maxDrop~} people left.");
    expect(r.text).toBe("About 630 people left.");
    const series = indexOf(
      'root = Artifact("t", "s", [], [line1])\nline1 = Line("Sign-ups", "Daily", ["Tue", "Wed", "Thu"], [["Sign-ups", [310, 420, 270]]])',
    );
    expect(resolveText("about {line1.avg~:Sign-ups} a day", series).text).toBe(
      "about 330 a day",
    );
  });

  it("rejects a rounded figure typed by hand", () => {
    expect(
      ungrounded("About 200 people signed up a day.", sourceNumbers(SOURCE)),
    ).toEqual(["200"]);
  });

  it("exempts small counts and the top of a percentage scale", () => {
    expect(
      ungrounded("3 teams reached 100 percent.", sourceNumbers(SOURCE)),
    ).toEqual([]);
  });
});

describe("extractProgram", () => {
  it("keeps statements from the first root and drops prose around them", () => {
    const reply = `Here is your artifact:\nroot = Artifact("t", "s", [], [para1])\npara1 = Paragraph("x")\nThat's all.`;
    expect(extractProgram(reply)).toBe(
      'root = Artifact("t", "s", [], [para1])\npara1 = Paragraph("x")',
    );
  });

  it("keeps a second program so the validator can see it was written twice", () => {
    const reply = `root = Artifact("a", "s", [], [])\nroot = Artifact("b", "s", [], [])`;
    expect(extractProgram(reply).match(/^root\s*=/gm)).toHaveLength(2);
  });
});
