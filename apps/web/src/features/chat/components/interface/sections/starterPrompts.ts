/**
 * Curated task prompts for the new-chat empty state, tagged by profession
 * archetype (the same 5-archetype bucketing the onboarding platform preview
 * uses). Selection guarantees at least one archetype-specific prompt when the
 * pool has one, and at least one zero-setup prompt so a fresh account with no
 * integrations always has a tap that pays off immediately.
 *
 * Every prompt is written the way the USER would say it — it lands in the
 * composer verbatim on tap.
 */

import {
  AiBrain01Icon,
  AlertCircleIcon,
  BookOpen01Icon,
  CalendarIcon,
  ChartIncreaseIcon,
  Clock01Icon,
  Github01Icon,
  GlobalIcon,
  HelpCircleIcon,
  type IconProps,
  Mail01Icon,
  Note01Icon,
  PencilEdit01Icon,
  QuillWrite01Icon,
  Rocket01Icon,
  SearchIcon,
  SparklesIcon,
  TaskAddIcon,
  ZapIcon,
} from "@icons";
import type { ComponentType } from "react";
import { getArchetype } from "@/features/onboarding/constants/platformPreviewMessages";
import type { ProfessionArchetype } from "@/features/onboarding/constants/platformPreviewMessages.types";

export interface StarterPrompt {
  prompt: string;
  icon: ComponentType<IconProps>;
  /** Undefined = shown to every archetype. */
  archetypes?: ProfessionArchetype[];
  /** Delivers value with zero integrations connected. */
  zeroSetup: boolean;
}

const STARTER_PROMPT_COUNT = 3;

const STARTER_PROMPTS: StarterPrompt[] = [
  // Universal — zero setup
  {
    prompt: "What can you actually do for me?",
    icon: SparklesIcon,
    zeroSetup: true,
  },
  { prompt: "Help me plan my day", icon: TaskAddIcon, zeroSetup: true },
  {
    prompt: "Set a goal and keep me on track",
    icon: Rocket01Icon,
    zeroSetup: true,
  },
  {
    prompt: "Remind me to drink water every 2 hours",
    icon: Clock01Icon,
    zeroSetup: true,
  },
  {
    prompt: "Give me a quick briefing on today's news",
    icon: GlobalIcon,
    zeroSetup: true,
  },
  {
    prompt: "Turn my messy notes into a todo list",
    icon: Note01Icon,
    zeroSetup: true,
  },
  {
    prompt: "Research something I've been putting off",
    icon: SearchIcon,
    zeroSetup: true,
  },
  {
    prompt: "Help me write a message I keep avoiding",
    icon: QuillWrite01Icon,
    zeroSetup: true,
  },

  // Universal — needs an integration (a tap becomes a connect funnel)
  { prompt: "Triage my inbox for today", icon: Mail01Icon, zeroSetup: false },
  { prompt: "Summarize my unread emails", icon: Mail01Icon, zeroSetup: false },
  {
    prompt: "What's on my calendar this week?",
    icon: CalendarIcon,
    zeroSetup: false,
  },
  {
    prompt: "Find me a free hour tomorrow",
    icon: CalendarIcon,
    zeroSetup: false,
  },
  {
    prompt: "Draft replies to emails waiting on me",
    icon: PencilEdit01Icon,
    zeroSetup: false,
  },

  // Builder
  {
    prompt: "Summarize my open pull requests",
    icon: Github01Icon,
    archetypes: ["builder"],
    zeroSetup: false,
  },
  {
    prompt: "Draft my standup update",
    icon: PencilEdit01Icon,
    archetypes: ["builder"],
    zeroSetup: true,
  },
  {
    prompt: "Help me think through a technical decision",
    icon: AiBrain01Icon,
    archetypes: ["builder"],
    zeroSetup: true,
  },
  {
    prompt: "Turn this week's work into release notes",
    icon: Note01Icon,
    archetypes: ["builder"],
    zeroSetup: true,
  },

  // Operator
  {
    prompt: "Draft my weekly status update",
    icon: PencilEdit01Icon,
    archetypes: ["operator"],
    zeroSetup: true,
  },
  {
    prompt: "Prep me for tomorrow's meetings",
    icon: CalendarIcon,
    archetypes: ["operator"],
    zeroSetup: false,
  },
  {
    prompt: "Turn my meeting notes into action items",
    icon: TaskAddIcon,
    archetypes: ["operator"],
    zeroSetup: true,
  },
  {
    prompt: "What's slipping that needs my attention?",
    icon: AlertCircleIcon,
    archetypes: ["operator"],
    zeroSetup: false,
  },

  // Founder
  {
    prompt: "Draft this month's investor update",
    icon: ChartIncreaseIcon,
    archetypes: ["founder"],
    zeroSetup: true,
  },
  {
    prompt: "Research my competitors for me",
    icon: SearchIcon,
    archetypes: ["founder"],
    zeroSetup: true,
  },
  {
    prompt: "Prioritize what needs me today",
    icon: ZapIcon,
    archetypes: ["founder"],
    zeroSetup: true,
  },
  {
    prompt: "Draft a follow-up for yesterday's call",
    icon: QuillWrite01Icon,
    archetypes: ["founder"],
    zeroSetup: false,
  },

  // Scholar
  {
    prompt: "Build me a study plan for this week",
    icon: BookOpen01Icon,
    archetypes: ["scholar"],
    zeroSetup: true,
  },
  {
    prompt: "Summarize a paper or article for me",
    icon: Note01Icon,
    archetypes: ["scholar"],
    zeroSetup: true,
  },
  {
    prompt: "Flag my upcoming deadlines",
    icon: Clock01Icon,
    archetypes: ["scholar"],
    zeroSetup: false,
  },
  {
    prompt: "Quiz me on what I'm studying",
    icon: HelpCircleIcon,
    archetypes: ["scholar"],
    zeroSetup: true,
  },
];

const shuffleArray = <T>(array: T[]): T[] => {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i--) {
    // False positive: cosmetic shuffle of starter-prompt suggestions — no
    // security property depends on this randomness.
    const j = Math.floor(Math.random() * (i + 1)); // NOSONAR typescript:S2245
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
};

export function pickStarterPrompts(
  profession: string | null | undefined,
): StarterPrompt[] {
  const archetype = getArchetype(profession ?? undefined);
  const eligible = STARTER_PROMPTS.filter(
    (p) => !p.archetypes || p.archetypes.includes(archetype),
  );

  const personaPool = shuffleArray(eligible.filter((p) => p.archetypes));
  const universalPool = shuffleArray(eligible.filter((p) => !p.archetypes));

  // One persona-specific prompt when the archetype has any, rest universal.
  const picked = [
    ...personaPool.slice(0, 1),
    ...universalPool,
    ...personaPool.slice(1),
  ].slice(0, STARTER_PROMPT_COUNT);

  // Guarantee one zero-setup anchor so there's always an instant-value tap.
  if (!picked.some((p) => p.zeroSetup)) {
    const anchor = shuffleArray(
      eligible.filter((p) => p.zeroSetup && !picked.includes(p)),
    )[0];
    if (anchor) picked[picked.length - 1] = anchor;
  }

  return shuffleArray(picked);
}
