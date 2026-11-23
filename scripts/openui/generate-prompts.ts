/**
 * Render the OpenUI component vocabularies the backend's models read.
 *
 * - comms: the official @openuidev/react-ui library plus the GAIA-only components in
 *   apps/web/src/config/openui/promptSpecs.ts, to apps/api/app/agents/prompts/openui_generated.txt.
 * - the artifact model: one prompt per kind from @gaia/artifacts, to
 *   apps/api/app/agents/prompts/artifacts/<kind>.txt.
 *
 * Run via `mise openui:prompts`; CI's openui-prompts check fails on drift.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  createLibrary,
  defineComponent,
  generatePrompt,
  type PromptSpec,
} from "@openuidev/react-lang";
import {
  openuiAdditionalRules,
  openuiExamples,
  openuiLibrary,
} from "@openuidev/react-ui/genui-lib";
import { GAIA_COMPONENT_SPECS } from "../../apps/web/src/config/openui/promptSpecs";
import { artifactPromptSpec } from "../../libs/artifacts/src/prompts";
import { ARTIFACT_KINDS } from "../../libs/shared/ts/src/artifacts/schema";

const PROMPTS_DIR = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../apps/api/app/agents/prompts",
);

// lang-core hardcodes this rule into every prompt; GAIA renders the user's real data, so it
// would tell the model to invent numbers. Throw if the wording moves, so a bump cannot bring it back.
const FABRICATE_DATA_RULE =
  "- When asked about data, generate realistic/plausible data\n";

/** The prompt text, without the invent-data rule and with no em/en dashes (banned in prompt prose). */
function render(spec: PromptSpec): string {
  const prompt = generatePrompt(spec);
  if (!prompt.includes(FABRICATE_DATA_RULE)) {
    throw new Error(
      "lang-core's plausible-data rule changed wording: re-check generatePrompt output",
    );
  }
  return prompt.replace(FABRICATE_DATA_RULE, "").replace(/[—–]/g, "-");
}

function write(path: string, prompt: string): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, prompt, "utf-8");
  console.log(`Wrote ${prompt.length} chars to ${path}`);
}

/** react-ui's library merged with GAIA's specs; a spec's component fn never feeds the prompt. */
function commsSpec(): PromptSpec {
  const gaiaSpec = createLibrary({
    components: GAIA_COMPONENT_SPECS.map((spec) =>
      defineComponent({
        name: spec.name,
        description: spec.description,
        props: spec.props,
        component: () => null,
      }),
    ),
    componentGroups: [
      {
        name: "GAIA Components",
        components: GAIA_COMPONENT_SPECS.map((spec) => spec.name),
      },
    ],
  }).toSpec();
  const reactUiSpec = openuiLibrary.toSpec();
  return {
    ...reactUiSpec,
    components: { ...reactUiSpec.components, ...gaiaSpec.components },
    componentGroups: [
      ...(reactUiSpec.componentGroups ?? []),
      ...(gaiaSpec.componentGroups ?? []),
    ],
    examples: openuiExamples,
    additionalRules: openuiAdditionalRules,
    // comms writes OpenUI inside :::openui fences mixed with prose, framed by
    // OPENUI_SURFACE_POLICY (Python); react-ui's "your ENTIRE response" preamble would contradict it.
    preamble: "",
  };
}

write(resolve(PROMPTS_DIR, "openui_generated.txt"), render(commsSpec()));
for (const kind of ARTIFACT_KINDS) {
  write(
    resolve(PROMPTS_DIR, "artifacts", `${kind}.txt`),
    render(artifactPromptSpec(kind)),
  );
}
