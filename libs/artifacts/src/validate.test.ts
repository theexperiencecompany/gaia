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

  it("rejects a slot inside a table cell, which would print as braces", () => {
    const result = validateArtifact(
      `root = Artifact("Atlas launch", "Week one", [], [funnel1, table1])\n${FUNNEL}\ntable1 = DataTable(null, ["Step", "Lost"], [0], [["Signed up", "{funnel1.maxDrop}"]])\n`,
      SOURCE,
    );
    expect(result.ok).toBe(false);
    expect(result.problems).toEqual([
      expect.stringContaining('table1 = DataTable(...): "{funnel1.maxDrop}"'),
    ]);
  });

  it("rejects a chart series that has a different number of values than labels", () => {
    const result = validateArtifact(
      `root = Artifact("Atlas launch", "Week one", [], [line1])\nline1 = Line("Signups", "Week one", ["Mon", "Tue"], [["Signups", [96]]])\n`,
      "Signups: 96.",
    );
    expect(result.problems).toEqual([
      'line1 = Line(...): series "Signups" has 1 values for 2 labels; give each label exactly one value',
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

  it("validates the program inside a reply and rejects one written twice", () => {
    const result = validateArtifact(
      'Here it is:\nroot = Artifact("a", "b", [], [])\nAnd again:\nroot = Artifact("a", "b", [], [])',
      "",
    );
    expect(result.program).toBe(
      'root = Artifact("a", "b", [], [])\nroot = Artifact("a", "b", [], [])',
    );
    expect(result.problems).toContain(
      "the program is written 2 times; write it once",
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

  describe("HtmlArtifact", () => {
    const CALCULATOR =
      '<form class="calculator" data-calc><div class="calc-grid"><div class="calc-inputs"><label class="calc-in"><span>Price</span><input type="number" name="price" value="465000" step="5000"></label><label class="calc-in"><span>Rate</span><input type="number" name="rate" value="3.4"></label></div><div class="calc-outputs"><div class="calc-out primary"><span>Interest</span><output data-formula="round(price * rate / 100)" data-prefix="" data-suffix="" data-decimals="0"></output></div></div></div></form>';
    const program = (html: string) =>
      `root = Artifact("Mortgage", "Try your numbers", [], [html1])\nhtml1 = HtmlArtifact("Calculator", ${JSON.stringify(html)})`;

    it("is allowed, with its input defaults ungrounded, when the request is interactive", () => {
      const result = validateArtifact(program(CALCULATOR), "", {
        interactive: true,
      });
      expect(result.problems).toEqual([]);
    });

    it("is rejected when the request asks for nothing to interact with", () => {
      const result = validateArtifact(program(CALCULATOR), "");
      expect(result.problems).toEqual([
        "html1 = HtmlArtifact(...): the request asks for nothing to interact with; use the other components",
      ]);
    });

    it.each([
      ['<div><script>fetch("https://x.io")</script></div>', "<script>"],
      ['<div style="color:red">x</div>', "style="],
      ['<button onclick="go()">x</button>', "on* event attribute"],
      ['<a href="https://evil.example">x</a>', "points at a URL"],
      ['<img src="data:image/png;base64,AA">', "loads content"],
    ])("rejects %s", (html, why) => {
      const result = validateArtifact(program(html), "", { interactive: true });
      expect(result.problems.some((p) => p.includes(why))).toBe(true);
    });

    it("rejects a formula that names no input or leaves the grammar", () => {
      const bad = CALCULATOR.replace(
        "round(price * rate / 100)",
        "price * tax",
      ).replace(
        'data-decimals="0">',
        'data-decimals="0"></output><output data-formula="alert(1);price">',
      );
      const result = validateArtifact(program(bad), "", { interactive: true });
      expect(result.problems).toEqual(
        expect.arrayContaining([
          expect.stringContaining('names "tax", which is no input'),
          expect.stringContaining("uses characters outside"),
        ]),
      );
    });
  });
});
