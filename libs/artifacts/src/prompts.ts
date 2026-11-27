/**
 * What each kind's system prompt teaches beyond the component signatures: the grounding rules
 * the validator enforces, the statement names it checks, and the HtmlArtifact rule. Rendered
 * to apps/api/app/agents/prompts/artifacts/<kind>.txt by scripts/openui/generate-prompts.ts.
 */
import type { PromptSpec } from "@openuidev/react-lang";
import { type ArtifactKind, KIND_COMPONENTS, STATEMENT_NAMES } from "./kinds";
import { artifactSpecLibrary } from "./specLibrary";
import { ARTIFACT_ROOT } from "./specs";

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

const HTML_ARTIFACT_RULE =
  "HtmlArtifact is only for a request that asks for inputs to play with (a calculator, a simulator, a small tool); everything else uses the other components. Its html is structure and classes only, and every result it shows is a data-formula over its inputs.";

function namingRule(components: readonly string[]): string {
  const names = components.flatMap((c) => {
    const name = STATEMENT_NAMES[c];
    return name ? [`${c}: ${name}1, ${name}2, ...`] : [];
  });
  return `Statement names: root, then for each component exactly this name plus a number counting from 1 per type. ${names.join("; ")}. Slots use these names, e.g. {funnel1.worstStepLoss}.`;
}

/** One kind's prompt spec: only its own components, so the prompt stays short and caches by prefix. */
export function artifactPromptSpec(kind: ArtifactKind): PromptSpec {
  const components = KIND_COMPONENTS[kind];
  const keep = new Set([ARTIFACT_ROOT, ...components]);
  const spec = artifactSpecLibrary.toSpec();
  return {
    ...spec,
    components: Object.fromEntries(
      Object.entries(spec.components).filter(([name]) => keep.has(name)),
    ),
    componentGroups: undefined,
    preamble: PREAMBLE,
    additionalRules: [
      namingRule(components),
      ...GROUNDING_RULES,
      ...(components.includes("HtmlArtifact") ? [HTML_ARTIFACT_RULE] : []),
    ],
  };
}
