import type { WorkflowCreatedData, WorkflowDraftData } from "@gaia/shared";
import { useRouter } from "expo-router";
import { Button, Chip } from "heroui-native";
import { useCallback } from "react";
import { Pressable, View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  FlashIcon,
  FlowIcon,
  PencilEdit01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { cronToHumanReadable } from "@/features/workflows/utils/cronUtils";

// ---------------------------------------------------------------------------
// Trigger display — mirrors web getTriggerDisplay() in WorkflowDraftCard /
// WorkflowCreatedCard. Same color tokens, same icon mapping.
// ---------------------------------------------------------------------------

interface TriggerDisplay {
  label: string;
  icon: React.ReactNode;
  textColor: string;
  bgClass: string;
}

function formatIntegrationLabel(slug?: string | null): string {
  if (!slug) return "Integration";
  return slug
    .split("_")
    .slice(0, 2)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

function getTriggerDisplay(
  type?: string,
  cron?: string | null,
  slug?: string | null,
): TriggerDisplay {
  switch (type) {
    case "manual":
      return {
        label: "Manual",
        icon: <AppIcon icon={FlashIcon} size={12} color="#a1a1aa" />,
        textColor: "#d4d4d8",
        bgClass: "bg-zinc-700/50",
      };
    case "scheduled":
      return {
        label: cron ? cronToHumanReadable(cron) : "Scheduled",
        icon: <AppIcon icon={Clock01Icon} size={12} color="#00bbff" />,
        textColor: "#00bbff",
        bgClass: "bg-[#00bbff]/15",
      };
    case "integration":
      return {
        label: formatIntegrationLabel(slug),
        icon: <AppIcon icon={Calendar03Icon} size={12} color="#a78bfa" />,
        textColor: "#c4b5fd",
        bgClass: "bg-purple-500/15",
      };
    default:
      return {
        label: "Unknown",
        icon: <AppIcon icon={FlashIcon} size={12} color="#a1a1aa" />,
        textColor: "#d4d4d8",
        bgClass: "bg-zinc-700/50",
      };
  }
}

// ---------------------------------------------------------------------------
// TriggerChip — visual parity with web's HeroUI <Chip> in flat variant.
// ---------------------------------------------------------------------------

function TriggerChip({ display }: { display: TriggerDisplay }) {
  return (
    <View
      className={`flex-row items-center gap-1.5 self-start rounded-full px-2.5 py-1 ${display.bgClass}`}
    >
      {display.icon}
      <Text
        className="text-xs font-medium"
        style={{ color: display.textColor }}
      >
        {display.label}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// WorkflowDraftCard — port of apps/web/src/features/workflows/components/
// WorkflowDraftCard.tsx
//
// Web uses a dashed warning border + absolutely-positioned "Draft" chip.
// Mobile keeps the same layout: warning-tinted shell, prominent FlowIcon
// avatar, trigger chip on the right of the header, description, and a
// "Review & Create" primary button. Tap navigates to the workflows screen
// (mobile parity for the web modal flow).
// ---------------------------------------------------------------------------

export function WorkflowDraftCard({ data }: { data: WorkflowDraftData }) {
  const router = useRouter();
  const trigger = getTriggerDisplay(
    data.trigger_type,
    data.cron_expression,
    data.trigger_slug,
  );

  const handleOpen = useCallback(() => {
    router.push("/(app)/workflows");
  }, [router]);

  return (
    <Pressable
      onPress={handleOpen}
      android_ripple={{ color: "rgba(255,255,255,0.05)" }}
      className="mx-4 my-1 rounded-2xl bg-zinc-800 p-4"
    >
      {/* Dashed warning ring — matches web's border-dashed border-warning/40 */}
      <View className="absolute inset-0 rounded-2xl border border-dashed border-amber-500/40" />

      {/* "Draft" badge — top-right pill */}
      <View className="absolute -top-2 right-3 self-start rounded-full bg-amber-500/20 px-2 py-0.5">
        <Text className="text-[11px] font-semibold text-amber-400">Draft</Text>
      </View>

      {/* Header: icon + title block + trigger chip */}
      <View className="flex-row items-start justify-between gap-3">
        <View className="flex-1 flex-row items-center gap-3">
          <View className="size-10 shrink-0 items-center justify-center rounded-xl bg-[#00bbff]/15">
            <AppIcon icon={FlowIcon} size={20} color="#00bbff" />
          </View>
          <View className="flex-1">
            <Text
              className="text-base font-semibold leading-tight text-zinc-100"
              numberOfLines={2}
            >
              {data.suggested_title}
            </Text>
            <Text className="mt-0.5 text-xs text-amber-400/80">
              Review to create workflow
            </Text>
          </View>
        </View>
        <View className="shrink-0">
          <TriggerChip display={trigger} />
        </View>
      </View>

      {/* Description */}
      {data.suggested_description ? (
        <Text
          className="mt-3 text-xs leading-relaxed text-zinc-400"
          numberOfLines={2}
        >
          {data.suggested_description}
        </Text>
      ) : null}

      {/* Integration setup hint */}
      {data.trigger_type === "integration" ? (
        <Text className="mt-2 text-xs text-zinc-500">
          Configure trigger settings to complete setup
        </Text>
      ) : null}

      {/* CTA — Review & Create */}
      <View className="mt-4">
        <Button size="sm" variant="primary" onPress={handleOpen}>
          <View className="flex-row items-center gap-1.5">
            <AppIcon icon={PencilEdit01Icon} size={14} color="#000000" />
            <Button.Label>Review & Create</Button.Label>
          </View>
        </Button>
      </View>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// WorkflowCreatedCard — port of apps/web/src/features/workflows/components/
// WorkflowCreatedCard.tsx
//
// Web uses a soft outline + success-tinted icon avatar + "Created" chip.
// Mobile mirrors that: success-green icon, "Created" chip on the right,
// description, trigger chip on its own row, and a "View & Edit" button.
// Tap navigates to /workflows/[id].
// ---------------------------------------------------------------------------

export function WorkflowCreatedCard({ data }: { data: WorkflowCreatedData }) {
  const router = useRouter();
  const trigger = getTriggerDisplay(
    data.trigger_config?.type,
    data.trigger_config?.cron_expression,
    data.trigger_config?.trigger_name,
  );

  const handleOpen = useCallback(() => {
    if (!data.id) {
      router.push("/(app)/workflows");
      return;
    }
    router.push({
      pathname: "/(app)/workflows/[id]",
      params: { id: data.id },
    });
  }, [router, data.id]);

  return (
    <Pressable
      onPress={handleOpen}
      android_ripple={{ color: "rgba(255,255,255,0.05)" }}
      className="mx-4 my-1 rounded-2xl bg-zinc-800 p-4"
    >
      {/* Subtle outline — matches web's outline-1 outline-zinc-800/50 */}
      <View className="absolute inset-0 rounded-2xl border border-zinc-700/40" />

      {/* Header: success icon + title block + Created chip */}
      <View className="flex-row items-start justify-between gap-3">
        <View className="flex-1 flex-row items-center gap-3">
          <View className="size-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15">
            <AppIcon icon={FlowIcon} size={20} color="#10b981" />
          </View>
          <View className="flex-1">
            <Text
              className="text-base font-semibold leading-tight text-zinc-100"
              numberOfLines={2}
            >
              {data.title}
            </Text>
            <Text className="mt-0.5 text-xs text-zinc-500">
              Workflow Created
            </Text>
          </View>
        </View>
        <Chip
          size="sm"
          variant="soft"
          color="success"
          animation="disable-all"
          className="shrink-0"
        >
          <View className="flex-row items-center gap-1">
            <AppIcon icon={CheckmarkCircle02Icon} size={12} color="#10b981" />
            <Chip.Label>Created</Chip.Label>
          </View>
        </Chip>
      </View>

      {/* Description */}
      {data.description ? (
        <Text
          className="mt-3 text-xs leading-relaxed text-zinc-400"
          numberOfLines={2}
        >
          {data.description}
        </Text>
      ) : null}

      {/* Trigger chip on its own row — matches web's third row */}
      <View className="mt-3">
        <TriggerChip display={trigger} />
      </View>

      {/* CTA — View & Edit */}
      <View className="mt-4">
        <Button size="sm" variant="primary" onPress={handleOpen}>
          <View className="flex-row items-center gap-1.5">
            <AppIcon icon={PencilEdit01Icon} size={14} color="#000000" />
            <Button.Label>View & Edit</Button.Label>
          </View>
        </Button>
      </View>
    </Pressable>
  );
}
