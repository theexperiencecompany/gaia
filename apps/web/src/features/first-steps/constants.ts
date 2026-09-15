import {
  BubbleChatIcon,
  PuzzleIcon,
  SmartPhone01Icon,
  WorkflowSquare05Icon,
} from "@icons";
import type { Transition } from "motion/react";
import type React from "react";
import type { FirstStepKey } from "@/types/features/firstStepsTypes";

export const FIRST_STEPS_QUERY_KEY = ["first-steps"] as const;

/** Slow poll that runs only while the checklist is still open, so a step
 * completed in another tab or on a bot shows up without a reload. */
export const FIRST_STEPS_POLL_INTERVAL_MS = 60_000;

/** Routes where the floating widget must stay hidden: the onboarding wizard,
 * and the dashboard, which already shows the full-width card. */
export const FIRST_STEPS_WIDGET_HIDDEN_PATHS: readonly string[] = [
  "/onboarding",
  "/dashboard",
];

export const SAY_HI_PROMPT = "What can you do for me?";

/** Under 300ms and ease-out, per the house animation rules. Shared by the
 * chevron, the collapse and the rows so all three move as one gesture. */
export const FIRST_STEPS_TRANSITION: Transition = {
  duration: 0.2,
  ease: [0.25, 1, 0.5, 1],
};

/** Small enough to read as one motion rather than five. */
export const FIRST_STEPS_ROW_STAGGER_SECONDS = 0.03;

export type FirstStepAction =
  | { kind: "chat"; prompt: string }
  | { kind: "navigate"; href: string };

export interface FirstStepDefinition {
  label: string;
  /** One line, always — every surface truncates rather than wraps. */
  description: string;
  icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  action: FirstStepAction;
}

export const FIRST_STEP_DEFINITIONS: Record<FirstStepKey, FirstStepDefinition> =
  {
    say_hi: {
      label: "Say hi",
      description: "See what GAIA can do for you",
      icon: BubbleChatIcon,
      action: { kind: "chat", prompt: SAY_HI_PROMPT },
    },
    connect_integration: {
      label: "Connect an integration",
      description: "Add Gmail, Calendar or Notion",
      icon: PuzzleIcon,
      action: { kind: "navigate", href: "/integrations" },
    },
    link_platform: {
      label: "Link a messaging app",
      description: "Chat from WhatsApp or Slack",
      icon: SmartPhone01Icon,
      action: { kind: "navigate", href: "/settings/linked-accounts" },
    },
    create_workflow: {
      label: "Create a workflow",
      description: "Put a weekly chore on autopilot",
      icon: WorkflowSquare05Icon,
      action: { kind: "navigate", href: "/workflows" },
    },
  };
