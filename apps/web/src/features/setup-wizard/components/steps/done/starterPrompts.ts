import { CodeIcon, GlobalIcon, Mail01Icon, SparklesIcon } from "@icons";
import type { CredentialProvider } from "@/features/settings/api/providersApi";

/** A starter prompt plus the capability it needs. Prompts whose capability
 * is missing are hidden — offering "search the web" with no search key just
 * teaches the user the app is broken. */
export interface StarterPrompt {
  prompt: string;
  icon: typeof GlobalIcon;
  /** Omitted for prompts that need nothing but chat. */
  requires?: CredentialProvider | "sandbox" | "inbox";
}

export const STARTER_PROMPTS: StarterPrompt[] = [
  {
    prompt: "What can you do for me?",
    icon: SparklesIcon,
  },
  {
    prompt: "Search the web for today's AI headlines",
    icon: GlobalIcon,
    requires: "tavily",
  },
  {
    prompt: "Run a Python script that prints hello world",
    icon: CodeIcon,
    requires: "sandbox",
  },
  {
    prompt: "Help me organize my inbox",
    icon: Mail01Icon,
    requires: "inbox",
  },
];
