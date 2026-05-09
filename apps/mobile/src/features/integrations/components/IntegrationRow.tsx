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
 * One row in the integrations list. Mirrors the web pattern in
 * `apps/web/src/features/integrations/components/IntegrationsList.tsx`:
 *
 *  - 40px logo + name (medium 600) + truncated description.
 *  - Trailing action is exactly one of:
 *      • `Connected` flat success chip (when connected)
 *      • `Connect` flat primary button (when available + not connected)
 *      • nothing (unavailable / pending)
 *  - Tapping the row anywhere opens the detail sheet, which is where
 *    "Disconnect" lives. The row never offers a destructive action.
 *  - Auth-type / managed-by / category badges live in the detail header,
 *    never on the row itself.
 */
export function IntegrationRow({
  integration,
  isPending,
  onPressRow,
  onPressConnect,
}: IntegrationRowProps) {
  const { fontSize, spacing } = useResponsive();

  const isConnected = integration.status === "connected";
  const isAvailable =
    integration.source === "custom" || integration.available !== false;

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
        {isPending ? (
          <IntegrationStatusPill status={integration.status} isPending />
        ) : isConnected ? (
          <IntegrationStatusPill status={integration.status} />
        ) : isAvailable && integration.status !== "created" ? (
          <Pressable
            onPress={() => onPressConnect(integration)}
            hitSlop={6}
            className="rounded-full bg-primary/15 px-3 py-1.5 active:bg-primary/25"
            accessibilityRole="button"
            accessibilityLabel={`Connect ${integration.name}`}
          >
            <Text className="text-primary text-[13px] font-semibold">
              Connect
            </Text>
          </Pressable>
        ) : integration.status === "created" ? (
          <IntegrationStatusPill status="created" />
        ) : null}
      </View>
    </PressableFeedback>
  );
}
