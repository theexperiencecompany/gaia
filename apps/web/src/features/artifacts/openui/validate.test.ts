import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { validateArtifact } from "./validate";

const fixture = (name: string): string =>
  readFileSync(resolve(__dirname, "__fixtures__", name), "utf8");

const SOURCE =
  "Funnel: signed up 1,840; connected a calendar 1,210; made a first plan 754; saw the paywall 612; paid 96.";
const FUNNEL =
  'funnel1 = Funnel("The paywall step loses the most people", "Week-one cohort", [["Signed up", 1840], ["Connected a calendar", 1210], ["Made a first plan", 754], ["Saw the paywall", 612], ["Paid", 96]])';

function withCallout(callout: string) {
  return validateArtifact(
    `root = Artifact("Atlas launch", "Week one", [], [funnel1, callout1])\n${FUNNEL}\ncallout1 = ${callout}\n`,
    SOURCE,
  );
}

describe("validateArtifact", () => {
  it.each(["launch", "report"])(
    "reports the prototype validator's problems for gpt-5.6-luna's first %s attempt",
    (doc) => {
      const result = validateArtifact(
        fixture(`first-${doc}.oui`),
        fixture(`brief-${doc}.txt`),
      );
      expect(result.ok).toBe(false);
      expect(result.problems).toEqual(
        JSON.parse(fixture(`first-${doc}.problems.json`)),
      );
    },
  );

  it("passes a grounded program and fills its slots", () => {
    const result = withCallout(
      'Callout("warn", "Biggest funnel loss", "{funnel1.maxDrop} people dropped at {funnel1.maxDropStage}.")',
    );
    expect(result.problems).toEqual([]);
    expect(result.resolved.callout1).toBe(
      "630 people dropped at Signed up to Connected a calendar.",
    );
    expect(result.components).toBe(3);
  });

  it("rejects a figure typed in prose that the brief never states", () => {
    const result = withCallout(
      'Callout("warn", "Biggest funnel loss", "142 people who made a first plan did not see the paywall.")',
    );
    expect(result.problems).toEqual([
      "callout1.text: 142 is not in the source data; state it with a slot such as {funnel1.maxDrop}, {line1.avg~} for a rounded figure, or leave it out",
    ]);
  });

  it("rejects a statement named off the list", () => {
    const result = validateArtifact(
      `root = Artifact("Atlas launch", "Week one", [], [signupFunnel])\n${FUNNEL.replace("funnel1", "signupFunnel")}\n`,
      SOURCE,
    );
    expect(result.problems).toEqual([
      "signupFunnel = Funnel(...): name it funnel1, funnel2, ... as the statement-name list says",
    ]);
  });

  it("rejects a program written twice and lines that are not statements", () => {
    const result = validateArtifact(
      'root = Artifact("a", "b", [], [])\nHere it is again:\nroot = Artifact("a", "b", [], [])',
      "",
    );
    expect(result.problems).toEqual(
      expect.arrayContaining([
        "the program is written 2 times; write it once",
        "1 lines are not statements; output only openui-lang",
      ]),
    );
  });

  it("rejects a reference that is never defined", () => {
    const result = validateArtifact(
      'root = Artifact("a", "b", [], [para1])',
      "",
    );
    expect(result.problems).toContain(
      '"para1" is referenced but never defined',
    );
  });
});
