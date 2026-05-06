import { Button, Chip, PressableFeedback } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { getCategoryLabel } from "../constants/categories";
import type { Integration } from "../types";
import { IntegrationLogo } from "./IntegrationLogo";
import { IntegrationStatusPill } from "./IntegrationStatusPill";

interface IntegrationRowProps {
  integration: Integration;
  isPending: boolean;
  onPressRow: (integration: Integration) => void;
  onPressAction: (integration: Integration) => void;
}

function AuthTypeChip({ authType }: { authType?: Integration["authType"] }) {
  if (!authType || authType === "none") return null;
  const label =
    authType === "oauth" ? "OAuth" : authType === "bearer" ? "Bearer" : "MCP";
  return (
    <Chip size="sm" variant="soft" color="default" animation="disable-all">
      <Chip.Label>{label}</Chip.Label>
    </Chip>
  );
}

function ManagedByChip({
  managedBy,
}: {
  managedBy?: Integration["managedBy"];
}) {
  if (!managedBy || managedBy === "self" || managedBy === "internal") {
    return null;
  }
  const label = managedBy === "composio" ? "Composio" : "MCP";
  return (
    <Chip size="sm" variant="soft" color="accent" animation="disable-all">
      <Chip.Label>{label}</Chip.Label>
    </Chip>
  );
}

export function IntegrationRow({
  integration,
  isPending,
  onPressRow,
  onPressAction,
}: IntegrationRowProps) {
  const { fontSize, spacing, moderateScale } = useResponsive();

  const isConnected = integration.status === "connected";
  const isAvailable =
    integration.source === "custom" || integration.available !== false;
  const toolCount = integration.tools?.length ?? 0;

  return (
    <PressableFeedback
      onPress={() => onPressRow(integration)}
      className="rounded-2xl bg-zinc-800/30"
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
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            flexWrap: "wrap",
          }}
        >
          <Text
            className="text-zinc-100"
            style={{
              fontSize: fontSize.sm,
              fontWeight: "700",
              flexShrink: 1,
            }}
            numberOfLines={1}
          >
            {integration.name}
          </Text>
          <Chip size="sm" variant="soft" color="accent" animation="disable-all">
            <Chip.Label>{getCategoryLabel(integration.category)}</Chip.Label>
          </Chip>
        </View>

        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
            marginTop: 3,
          }}
        >
          <AuthTypeChip authType={integration.authType} />
          <ManagedByChip managedBy={integration.managedBy} />
          {isConnected && toolCount > 0 ? (
            <Text
              className="text-zinc-500"
              style={{ fontSize: fontSize.xs - 2 }}
            >
              {toolCount} {toolCount === 1 ? "tool" : "tools"}
            </Text>
          ) : null}
        </View>
      </View>

      <View style={{ alignItems: "flex-end", gap: 6 }}>
        <IntegrationStatusPill
          status={integration.status}
          isPending={isPending}
        />
        {!isPending && isConnected ? (
          <Button
            size="sm"
            variant="danger-soft"
            onPress={() => onPressAction(integration)}
            style={{ borderRadius: moderateScale(12, 0.5) }}
          >
            <Button.Label>Disconnect</Button.Label>
          </Button>
        ) : !isPending && isAvailable && integration.status !== "created" ? (
          <Button
            size="sm"
            variant="tertiary"
            onPress={() => onPressAction(integration)}
            style={{ borderRadius: moderateScale(12, 0.5) }}
          >
            <Button.Label>Connect</Button.Label>
          </Button>
        ) : null}
      </View>
    </PressableFeedback>
  );
}
