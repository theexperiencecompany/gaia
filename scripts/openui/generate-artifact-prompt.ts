/**
 * Generate the artifact model's per-kind system prompts.
 *
 * The artifact library (apps/web/src/features/artifacts/openui/specs.ts plus react-ui's
 * PieChart, Slice and CodeBlock) is the single source for the renderer, the validator and
 * these prompts. Each kind keeps only its own components, so its prompt stays short and its
 * static text caches by prefix. Writes apps/api/app/agents/prompts/artifacts/<kind>.txt.
 *
 * Run via `pnpm openui:gen-artifact-prompts`. A pre-commit hook fails on drift.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { generatePrompt } from "@openuidev/react-lang";
import {
  ARTIFACT_KINDS,
  type ArtifactKind,
  KIND_COMPONENTS,
  STATEMENT_NAMES,
} from "../../apps/web/src/features/artifacts/openui/kinds";
import { artifactSpecLibrary } from "../../apps/web/src/features/artifacts/openui/specLibrary";
import { ARTIFACT_ROOT } from "../../apps/web/src/features/artifacts/openui/specs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = resolve(
  __dirname,
  "../../apps/api/app/agents/prompts/artifacts",
);

const PREAMBLE =
  "Your entire response is openui-lang code that renders one artifact. Write root = Artifact(...) first, then the data statements (charts, funnels, tables, stats), then the text statements, each exactly once. Output only openui-lang statements.";

const GROUNDING_RULES = [
  "Use only the facts in the request. Never invent a number, a name or a date.",
  "Grounded figures: never type a number you computed. Every figure in text must be in the request as written, or a slot {statement.key} that code fills from that statement's data.",
  'Averages, totals, differences, shares and percentage changes are always slots, never typed: write "{line1.avg:Pilot} a week against {line1.avg:Baseline}", not "209 against 216". Write every chart, funnel and table statement before any text statement that has a slot; root lists the order readers see.',
  'Approximate figures are slots too: add ~ after the key for a rounded value, e.g. "about {line1.avg~:Sign-ups} a day" (prints about 260). Never type a rounded number yourself.',
  'Funnel slots: first, last, maxDrop, maxDropStage (largest absolute drop), worstStep, worstStepLoss (largest share lost), overall. Example: "{funnel1.worstStep} loses {funnel1.worstStepLoss} of people."',
  'Line, Area, Bars, StackedBars slots, each with an optional :Series name: total, max, maxLabel, min, minLabel, avg, first, last, change, changePct. Example: "{line1.total} sign-ups, peaking on {line1.maxLabel:Sign-ups}."',
  "DataTable slots, each with an optional :Column name: sum, max, maxRow, min, minRow, count. Gauge slots: value, target, gap. Heatmap slots: max, maxCell, total.",
  "Chart only data the request gives in full; never fill gaps with estimates. Leave optional arguments out rather than passing null.",
  "Write the text like a person: open on the point, plain words, varied sentence length, a clear position. No filler, no hype words, no em or en dashes. Do not overcorrect into a gimmicky voice.",
];

function namingRule(components: readonly string[]): string {
  const names = components
    .filter((c) => STATEMENT_NAMES[c])
    .map((c) => `${c}: ${STATEMENT_NAMES[c]}1, ${STATEMENT_NAMES[c]}2, ...`);
  return `Statement names: root, then for each component exactly this name plus a number counting from 1 per type. ${names.join("; ")}. Slots use these names, e.g. {funnel1.worstStepLoss}.`;
}

// lang-core hardcodes this rule into every prompt; artifacts render the user's real data.
const FABRICATE_DATA_RULE =
  "- When asked about data, generate realistic/plausible data\n";

const HTML_ARTIFACT_RULE =
  "HtmlArtifact is only for a request that asks for inputs to play with (a calculator, a simulator, a small tool); everything else uses the other components. Its html is structure and classes only, and every result it shows is a data-formula over its inputs.";

function kindRules(kind: ArtifactKind): string[] {
  return KIND_COMPONENTS[kind].includes("HtmlArtifact")
    ? [HTML_ARTIFACT_RULE]
    : [];
}

function promptFor(kind: ArtifactKind): string {
  const keep = new Set([ARTIFACT_ROOT, ...KIND_COMPONENTS[kind]]);
  const spec = artifactSpecLibrary.toSpec();
  const prompt = generatePrompt({
    ...spec,
    components: Object.fromEntries(
      Object.entries(spec.components).filter(([name]) => keep.has(name)),
    ),
    componentGroups: undefined,
    preamble: PREAMBLE,
    additionalRules: [
      namingRule(KIND_COMPONENTS[kind]),
      ...GROUNDING_RULES,
      ...kindRules(kind),
    ],
  });
  if (!prompt.includes(FABRICATE_DATA_RULE)) {
    throw new Error(
      "lang-core's plausible-data rule changed wording: re-check generatePrompt output",
    );
  }
  // the prompts directory forbids em/en dashes in prompt prose
  return prompt.replace(FABRICATE_DATA_RULE, "").replace(/[—–]/g, "-");
}

mkdirSync(OUTPUT_DIR, { recursive: true });
for (const kind of ARTIFACT_KINDS) {
  const path = resolve(OUTPUT_DIR, `${kind}.txt`);
  const prompt = promptFor(kind);
  writeFileSync(path, prompt, "utf-8");
  console.log(`Wrote ${prompt.length} chars to ${path}`);
}
