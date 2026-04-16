import type { WorkflowCreatedData, WorkflowDraftData } from "@gaia/shared";
import { View } from "react-native";
import {
  AppIcon,
  CheckmarkCircle02Icon,
  WorkflowSquare10Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  SectionLabel,
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Helpers -----------------------------------------------------------------

function formatTriggerType(type: string): string {
  switch (type) {
    case "manual":
      return "Manual";
    case "scheduled":
      return "Scheduled";
    case "integration":
      return "Integration";
    default:
      return type;
  }
}

// -- Draft card --------------------------------------------------------------

export function WorkflowDraftCard({ data }: { data: WorkflowDraftData }) {
  const title = data.suggested_title ?? "Workflow Draft";
  const description = data.suggested_description;
  const trigger = data.trigger_type;
  const cron = data.cron_expression;
  const triggerSlug = data.trigger_slug;

  return (
    <ToolCardShell>
      <View className="flex-row items-center gap-3 mb-3">
        <View className="w-8 h-8 rounded-full bg-zinc-700 items-center justify-center">
          <AppIcon icon={WorkflowSquare10Icon} size={16} color="#00bbff" />
        </View>
        <View className="flex-1">
          <View className="flex-row items-center gap-2">
            <View className="h-2 w-2 rounded-full bg-yellow-500" />
            <Text className="text-zinc-100 text-base font-semibold">
              {title}
            </Text>
          </View>
          <Text className="text-zinc-500 text-xs mt-0.5">Draft workflow</Text>
        </View>
      </View>

      {description ? (
        <ToolCardInner dense>
          <Text className="text-zinc-300 text-sm">{description}</Text>
        </ToolCardInner>
      ) : null}

      {data.prompt ? (
        <View className="mt-2">
          <SectionLabel>PROMPT</SectionLabel>
          <ToolCardInner dense>
            <Text className="text-zinc-300 text-xs">{data.prompt}</Text>
          </ToolCardInner>
        </View>
      ) : null}

      {trigger ? (
        <View className="mt-2">
          <SectionLabel>TRIGGER</SectionLabel>
          <ToolCardInner dense>
            <View className="flex-row items-center gap-2">
              <Text className="text-zinc-100 text-sm font-medium">
                {formatTriggerType(trigger)}
              </Text>
              {cron ? (
                <Text className="text-zinc-500 text-xs">· {cron}</Text>
              ) : null}
              {triggerSlug ? (
                <Text className="text-zinc-500 text-xs">· {triggerSlug}</Text>
              ) : null}
            </View>
          </ToolCardInner>
        </View>
      ) : null}
    </ToolCardShell>
  );
}

// -- Created card ------------------------------------------------------------

export function WorkflowCreatedCard({ data }: { data: WorkflowCreatedData }) {
  const title = data.title ?? "Workflow";
  const description = data.description;
  const trigger = data.trigger_config?.type;
  const cron = data.trigger_config?.cron_expression;
  const triggerName = data.trigger_config?.trigger_name;
  const activated = data.activated;

  return (
    <ToolCardShell>
      <View className="flex-row items-center gap-3 mb-3">
        <View className="w-8 h-8 rounded-full bg-zinc-700 items-center justify-center">
          <AppIcon icon={WorkflowSquare10Icon} size={16} color="#10b981" />
        </View>
        <View className="flex-1">
          <View className="flex-row items-center gap-2">
            <View className="h-2 w-2 rounded-full bg-emerald-500" />
            <Text className="text-zinc-100 text-base font-semibold">
              {title}
            </Text>
          </View>
          <Text className="text-zinc-500 text-xs mt-0.5">
            {activated ? "Workflow active" : "Workflow created"}
          </Text>
        </View>
        {activated ? (
          <AppIcon icon={CheckmarkCircle02Icon} size={18} color="#10b981" />
        ) : null}
      </View>

      {description ? (
        <ToolCardInner dense>
          <Text className="text-zinc-300 text-sm">{description}</Text>
        </ToolCardInner>
      ) : null}

      {trigger ? (
        <View className="mt-2">
          <SectionLabel>TRIGGER</SectionLabel>
          <ToolCardInner dense>
            <View className="flex-row items-center gap-2 flex-wrap">
              <Text className="text-zinc-100 text-sm font-medium">
                {formatTriggerType(trigger)}
              </Text>
              {cron ? (
                <Text className="text-zinc-500 text-xs">· {cron}</Text>
              ) : null}
              {triggerName ? (
                <Text className="text-zinc-500 text-xs">· {triggerName}</Text>
              ) : null}
            </View>
          </ToolCardInner>
        </View>
      ) : null}
    </ToolCardShell>
  );
}
