import { CodeIcon, GlobalIcon, Mail01Icon, SparklesIcon } from "@icons";
import type { ProviderFeature } from "@shared/api/generated";

/** A starter prompt plus the feature it needs. Prompts whose feature is off
 * are hidden — offering "run a script" with no sandbox just teaches the user
 * the app is broken. */
export interface StarterPrompt {
  prompt: string;
  icon: typeof GlobalIcon;
  /** Omitted for prompts that need nothing but chat. */
  requires?: ProviderFeature;
}

export const STARTER_PROMPTS: StarterPrompt[] = [
  {
    prompt: "What can you do for me?",
    icon: SparklesIcon,
  },
  {
    prompt: "Search the web for today's AI headlines",
    icon: GlobalIcon,
    requires: "web_search",
  },
  {
    prompt: "Run a Python script that prints hello world",
    icon: CodeIcon,
    requires: "code_running",
  },
  {
    prompt: "Help me organize my inbox",
    icon: Mail01Icon,
    requires: "integrations",
  },
];
