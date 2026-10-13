import { CONNECT_ACTION_LABEL, integrationConnectionState } from "@gaia/shared";
import { PressableFeedback } from "heroui-native";
import { Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Integration } from "../types";
import { IntegrationLogo } from "./IntegrationLogo";
import { IntegrationStatusPill } from "./IntegrationStatusPill";

interface IntegrationRowProps {
  integration: Integration;
  isPending: boolean;
  onPressRow: (integration: Integration) => void;
  onPressConnect: (integration: Integration) => void;
}

/**
 * One row in the integrations list, mirroring web's IntegrationsList.tsx: 40px
 * logo + name + truncated description; trailing action is exactly one of
 * Connected chip, Disconnected chip + Reconnect, Connect button, or nothing.
 * Tapping opens the detail sheet (where Disconnect lives); auth-type/managed-by/
 * category badges live only in the detail header, never on the row.
 */
export function IntegrationRow({
  integration,
  isPending,
  onPressRow,
  onPressConnect,
}: IntegrationRowProps) {
  const { fontSize, spacing } = useResponsive();

  return (
    <PressableFeedback
      onPress={() => onPressRow(integration)}
      className="rounded-2xl"
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm + 2,
      }}
    >
      <View style={{ marginRight: spacing.sm + 4 }}>
        <IntegrationLogo integration={integration} size={40} />
      </View>

      <View style={{ flex: 1, minWidth: 0, marginRight: spacing.sm }}>
        <Text
          className="text-zinc-100"
          style={{
            fontSize: fontSize.sm,
            fontWeight: "600",
          }}
          numberOfLines={1}
        >
          {integration.name}
        </Text>
        {integration.description ? (
          <Text
            className="text-zinc-400"
            style={{ fontSize: fontSize.xs, marginTop: 2 }}
            numberOfLines={1}
          >
            {integration.description}
          </Text>
        ) : null}
      </View>

      <View style={{ alignItems: "flex-end" }}>
        <IntegrationRowAction
          integration={integration}
          isPending={isPending}
          onPressConnect={onPressConnect}
        />
      </View>
    </PressableFeedback>
  );
}

type RowActionKind = "pending" | "connected" | "connect" | "awaiting" | "none";

function resolveRowAction(
  integration: Integration,
  isPending: boolean,
): RowActionKind {
  const state = integrationConnectionState(integration.status);
  if (isPending) return "pending";
  if (state === "connected") return "connected";
  if (state === "pending") return "awaiting";
  const isAvailable =
    integration.source === "custom" || integration.available !== false;
  if (isAvailable || state === "expired") return "connect";
  return "none";
}

function ConnectButton({
  integration,
  onPressConnect,
}: {
  integration: Integration;
  onPressConnect: (integration: Integration) => void;
}) {
  const state = integrationConnectionState(integration.status);
  const isExpired = state === "expired";
  return (
    <Pressable
      onPress={() => onPressConnect(integration)}
      hitSlop={6}
      className={
        isExpired
          ? "rounded-full bg-amber-500/15 px-3 py-1.5 active:bg-amber-500/25"
          : "rounded-full bg-primary/15 px-3 py-1.5 active:bg-primary/25"
      }
      accessibilityRole="button"
      accessibilityLabel={`${CONNECT_ACTION_LABEL[state]} ${integration.name}`}
    >
      <Text
        className={
          isExpired
            ? "text-amber-500 text-[13px] font-semibold"
            : "text-primary text-[13px] font-semibold"
        }
      >
        {CONNECT_ACTION_LABEL[state]}
      </Text>
    </Pressable>
  );
}

function IntegrationRowAction({
  integration,
  isPending,
  onPressConnect,
}: Pick<IntegrationRowProps, "integration" | "isPending" | "onPressConnect">) {
  const kind = resolveRowAction(integration, isPending);
  if (kind === "pending") {
    return <IntegrationStatusPill status={integration.status} isPending />;
  }
  if (kind === "connected") {
    return <IntegrationStatusPill status={integration.status} />;
  }
  if (kind === "awaiting") return <IntegrationStatusPill status="created" />;
  if (kind === "connect") {
    return (
      <ConnectButton
        integration={integration}
        onPressConnect={onPressConnect}
      />
    );
  }
  return null;
}
