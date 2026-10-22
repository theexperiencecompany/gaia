"use client";

import dynamic from "next/dynamic";
import type { ComponentType } from "react";

const demos: Record<string, ComponentType> = {
  "smart-chat": dynamic(() => import("./demos/SmartChatDemo")),
  "deep-research": dynamic(() => import("./demos/DeepResearchDemo")),
  memory: dynamic(() => import("./demos/MemoryDemo")),
  "proactive-ai": dynamic(() => import("./demos/ProactiveAIDemo")),
  "image-generation": dynamic(() => import("./demos/ImageGenerationDemo")),
  "code-execution": dynamic(() => import("./demos/CodeExecutionDemo")),
  "rich-responses": dynamic(() => import("./demos/RichResponsesDemo")),
  todos: dynamic(() => import("./demos/TodosDemo")),
  calendar: dynamic(() => import("./demos/CalendarDemo")),
  email: dynamic(() => import("./demos/EmailDemo")),
  goals: dynamic(() => import("./demos/GoalsDemo")),
  reminders: dynamic(() => import("./demos/RemindersDemo")),
  pins: dynamic(() => import("./demos/PinsDemo")),
  dashboard: dynamic(() => import("./demos/DashboardDemo")),
  workflows: dynamic(() => import("./demos/WorkflowsDemo")),
  "scheduled-automation": dynamic(
    () => import("./demos/ScheduledAutomationDemo"),
  ),
  "event-triggers": dynamic(() => import("./demos/EventTriggersDemo")),
  "document-generation": dynamic(
    () => import("./demos/DocumentGenerationDemo"),
  ),
  skills: dynamic(() => import("./demos/SkillsDemo")),
  integrations: dynamic(() => import("./demos/IntegrationsDemo")),
  marketplace: dynamic(() => import("./demos/MarketplaceDemo")),
  "mcp-support": dynamic(() => import("./demos/MCPSupportDemo")),
  "custom-integrations": dynamic(
    () => import("./demos/CustomIntegrationsDemo"),
  ),
  contacts: dynamic(() => import("./demos/ContactsDemo")),
  subagents: dynamic(() => import("./demos/SubagentsDemo")),
  voice: dynamic(() => import("./demos/VoiceDemo")),
  "slack-bot": dynamic(() => import("./demos/SlackBotDemo")),
  "discord-bot": dynamic(() => import("./demos/DiscordBotDemo")),
  "telegram-bot": dynamic(() => import("./demos/TelegramBotDemo")),
  mobile: dynamic(() => import("./demos/MobileDemo")),
};

interface Props {
  demoComponent: string;
}

export function FeatureDemoWrapper({ demoComponent }: Props) {
  const Demo = demos[demoComponent];
  if (!Demo) return null;
  return <Demo />;
}
