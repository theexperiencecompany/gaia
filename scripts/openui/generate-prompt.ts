/**
 * Generate the backend LLM's OpenUI component vocabulary.
 *
 * The merged component set (the official `@openuidev/react-ui` library + the
 * GAIA-only components in `apps/web/src/config/openui/promptSpecs.ts`) is the
 * single source of truth for both the renderer and the LLM prompt. This script
 * renders that set to an openui-lang system prompt and writes it to
 * `apps/api/app/agents/prompts/openui_generated.txt`.
 *
 * Run via `pnpm openui:gen-prompt`. A pre-commit hook fails on drift, so the
 * artifact is always in sync with the component specs.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  createLibrary,
  defineComponent,
  generatePrompt,
} from "@openuidev/react-lang";
import {
  openuiAdditionalRules,
  openuiExamples,
  openuiLibrary,
} from "@openuidev/react-ui/genui-lib";
import { GAIA_COMPONENT_SPECS } from "../../apps/web/src/config/openui/promptSpecs";

const __dirname = dirname(fileURLToPath(import.meta.url));

const OUTPUT_PATH = resolve(
  __dirname,
  "../../apps/api/app/agents/prompts/openui_generated.txt",
);

// No-op library from the GAIA specs — the `component` fn is irrelevant for
// prompt generation, only name/description/props feed the rendered signature.
const gaiaLibrary = createLibrary({
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
});

const reactUiSpec = openuiLibrary.toSpec();
const gaiaSpec = gaiaLibrary.toSpec();

const mergedSpec = {
  ...reactUiSpec,
  components: { ...reactUiSpec.components, ...gaiaSpec.components },
  componentGroups: [
    ...(reactUiSpec.componentGroups ?? []),
    ...(gaiaSpec.componentGroups ?? []),
  ],
  examples: openuiExamples,
  additionalRules: openuiAdditionalRules,
};

const prompt = generatePrompt(mergedSpec);

mkdirSync(dirname(OUTPUT_PATH), { recursive: true });
writeFileSync(OUTPUT_PATH, prompt, "utf-8");

console.log(`Wrote ${prompt.length} chars to ${OUTPUT_PATH}`);
