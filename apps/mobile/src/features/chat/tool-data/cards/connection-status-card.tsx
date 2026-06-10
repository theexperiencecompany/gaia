import { useRouter } from "expo-router";
import { Button, Chip } from "heroui-native";
import { useCallback } from "react";
import { View } from "react-native";
import {
  AlertCircleIcon,
  CheckmarkCircle02Icon,
  ConnectIcon,
} from "@/components/icons";
import { AppIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import {
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";

// ---------------------------------------------------------------------------
// Types
//
// Backend ships either a single-integration probe (legacy `status` shape)
// or a list summary (`{ integrations: [...] }`). The card normalizes both
// to a single rendering pipeline so the same chat tool can describe one or
// many integrations.
// ---------------------------------------------------------------------------

export type ConnectionStatus = "connected" | "disconnected" | "error";

export interface ConnectionStatusItem {
  id?: string;
  name?: string;
  connected?: boolean;
  status?: ConnectionStatus;
  message?: string;
  error_detail?: string;
  icon_url?: string | null;
}

export interface ConnectionStatusData {
  // Single-integration shape (legacy).
  integration_id?: string;
  integration_name?: string;
  status?: ConnectionStatus;
  message?: string;
  error_detail?: string;
  icon_url?: string | null;
  // List shape (current backend / fixture).
  integrations?: ConnectionStatusItem[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatIntegrationName(id?: string | null): string {
  if (!id) return "Integration";
  return id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function resolveStatus(item: ConnectionStatusItem): ConnectionStatus {
  if (item.status) return item.status;
  return item.connected ? "connected" : "disconnected";
}

interface NormalizedItem {
  id: string;
  name: string;
  status: ConnectionStatus;
  message?: string;
  error_detail?: string;
  iconUrl?: string | null;
}

function normalize(data: ConnectionStatusData): NormalizedItem[] {
  if (Array.isArray(data.integrations) && data.integrations.length > 0) {
    return data.integrations.map((item) => {
      const id = item.id ?? item.name ?? "";
      return {
        id,
        name: item.name ?? formatIntegrationName(item.id),
        status: resolveStatus(item),
        message: item.message,
        error_detail: item.error_detail,
        iconUrl: item.icon_url,
      };
    });
  }
  // Legacy single-integration shape.
  const id = data.integration_id ?? data.integration_name ?? "";
  if (!id && !data.status) return [];
  return [
    {
      id,
      name: data.integration_name ?? formatIntegrationName(data.integration_id),
      status: data.status ?? "disconnected",
      message: data.message,
      error_detail: data.error_detail,
      iconUrl: data.icon_url,
    },
  ];
}

// ---------------------------------------------------------------------------
// StatusBadge — Chip styled with semantic color tokens.
// ---------------------------------------------------------------------------

interface StatusBadgeProps {
  status: ConnectionStatus;
}

function StatusBadge({ status }: StatusBadgeProps) {
  switch (status) {
    case "connected":
      return (
        <Chip size="sm" variant="soft" color="success" animation="disable-all">
          <View className="flex-row items-center gap-1">
            <AppIcon icon={CheckmarkCircle02Icon} size={10} color="#22c55e" />
            <Chip.Label>Connected</Chip.Label>
          </View>
        </Chip>
      );
    case "error":
      return (
        <Chip size="sm" variant="soft" color="danger" animation="disable-all">
          <View className="flex-row items-center gap-1">
            <AppIcon icon={AlertCircleIcon} size={10} color="#ef4444" />
            <Chip.Label>Error</Chip.Label>
          </View>
        </Chip>
      );
    default:
      return (
        <Chip size="sm" variant="soft" color="default" animation="disable-all">
          <View className="flex-row items-center gap-1">
            <View className="h-1.5 w-1.5 rounded-full bg-zinc-400" />
            <Chip.Label>Disconnected</Chip.Label>
          </View>
        </Chip>
      );
  }
}

// ---------------------------------------------------------------------------
// IntegrationStatusRow — single row inside the list shell.
// ---------------------------------------------------------------------------

function IntegrationStatusRow({ item }: { item: NormalizedItem }) {
  const icon = item.id
    ? getToolCategoryIcon(
        item.id,
        { size: 20, showBackground: false },
        item.iconUrl ?? undefined,
      )
    : null;

  return (
    <ToolCardInner dense>
      <View className="flex-row items-start gap-3">
        <View className="shrink-0 pt-0.5">
          {icon ?? <AppIcon icon={ConnectIcon} size={18} color="#a1a1aa" />}
        </View>

        <View className="min-w-0 flex-1 gap-1">
          <View className="flex-row flex-wrap items-center gap-2">
            <Text className="text-sm font-medium text-zinc-100">
              {item.name}
            </Text>
            <StatusBadge status={item.status} />
          </View>

          {item.message ? (
            <Text className="text-xs text-zinc-400" numberOfLines={2}>
              {item.message}
            </Text>
          ) : null}

          {item.error_detail ? (
            <View className="mt-1 flex-row items-start gap-2 rounded-xl bg-red-500/10 p-2">
              <View className="pt-0.5">
                <AppIcon icon={AlertCircleIcon} size={12} color="#ef4444" />
              </View>
              <Text
                className="flex-1 text-xs leading-[18px] text-red-400"
                numberOfLines={3}
              >
                {item.error_detail}
              </Text>
            </View>
          ) : null}
        </View>
      </View>
    </ToolCardInner>
  );
}

// ---------------------------------------------------------------------------
// ConnectionStatusCard — list of integration statuses with a manage CTA.
//
// Renders both single-integration and list-shape payloads. Matches the
// chat tool card styling contract (zinc-800 shell, zinc-900 inner rows,
// no borders) and uses heroui-native primitives for chips/buttons so the
// theming stays consistent with other tool cards.
// ---------------------------------------------------------------------------

export function ConnectionStatusCard({ data }: { data: ConnectionStatusData }) {
  const router = useRouter();
  const items = normalize(data);

  const handleManage = useCallback(() => {
    router.push("/(app)/integrations");
  }, [router]);

  if (items.length === 0) {
    return null;
  }

  const connectedCount = items.filter((i) => i.status === "connected").length;
  const totalCount = items.length;
  const isSingle = items.length === 1;

  return (
    <ToolCardShell>
      {/* Header — icon + title + summary chip */}
      <View className="mb-3 flex-row items-start justify-between gap-3">
        <View className="flex-1 flex-row items-center gap-3">
          <View className="size-10 shrink-0 items-center justify-center rounded-xl bg-zinc-700/60">
            <AppIcon icon={ConnectIcon} size={20} color="#d4d4d8" />
          </View>
          <View className="flex-1">
            <Text className="text-base font-semibold leading-tight text-zinc-100">
              {isSingle ? items[0].name : "Connection Status"}
            </Text>
            <Text className="mt-0.5 text-xs text-zinc-500">
              {isSingle
                ? "Integration status"
                : `${connectedCount} of ${totalCount} connected`}
            </Text>
          </View>
        </View>
        {isSingle ? (
          <View className="shrink-0">
            <StatusBadge status={items[0].status} />
          </View>
        ) : (
          <Chip
            size="sm"
            variant="soft"
            color="default"
            animation="disable-all"
            className="shrink-0"
          >
            <Chip.Label>{`${totalCount}`}</Chip.Label>
          </Chip>
        )}
      </View>

      {/* Single-integration view inlines message + error detail without an
          extra wrapper row to mirror the previous compact layout. */}
      {isSingle ? (
        <>
          {items[0].message ? (
            <Text className="mb-3 text-xs text-zinc-400">
              {items[0].message}
            </Text>
          ) : null}
          {items[0].error_detail ? (
            <View className="mb-3 flex-row items-start gap-2 rounded-xl bg-red-500/10 p-3">
              <AppIcon icon={AlertCircleIcon} size={14} color="#ef4444" />
              <Text className="flex-1 text-xs leading-[18px] text-red-400">
                {items[0].error_detail}
              </Text>
            </View>
          ) : null}
        </>
      ) : (
        <View className="mb-3 gap-2">
          {items.map((item, index) => (
            <IntegrationStatusRow
              key={item.id || `${item.name}-${index}`}
              item={item}
            />
          ))}
        </View>
      )}

      {/* Manage button — heroui-native Button keeps the CTA surface
          consistent with other tool cards. */}
      <Button size="sm" variant="secondary" onPress={handleManage}>
        <Button.Label>Manage Integrations</Button.Label>
      </Button>
    </ToolCardShell>
  );
}
