import { Image } from "expo-image";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { getCategoryLabel } from "../constants/categories";
import { getIntegrationLogo } from "../constants/logos";
import type { Integration } from "../types";
import { IntegrationStatusPill } from "./IntegrationStatusPill";

interface IntegrationDetailHeaderProps {
  integration: Integration;
}

interface BadgeProps {
  label: string;
  color: string;
  bg: string;
}

function Badge({ label, color, bg }: BadgeProps) {
  return (
    <View className="rounded-full px-2.5 py-1" style={{ backgroundColor: bg }}>
      <Text className="text-xs font-medium" style={{ color }}>
        {label}
      </Text>
    </View>
  );
}

function getAuthTypeLabel(authType: string): string {
  if (authType === "oauth") return "OAuth";
  if (authType === "bearer") return "Bearer Token";
  if (authType === "none") return "No Auth";
  return authType;
}

function getManagedByLabel(managedBy: string): string {
  if (managedBy === "composio") return "Composio";
  if (managedBy === "mcp") return "MCP";
  if (managedBy === "internal") return "Internal";
  return "Self";
}

export function IntegrationDetailHeader({
  integration,
}: IntegrationDetailHeaderProps) {
  const { fontSize, spacing } = useResponsive();

  const authType = integration.authType ?? "oauth";
  const managedBy = integration.managedBy ?? "self";
  const isCustom = integration.source === "custom";
  const logoUri = getIntegrationLogo(integration.id, integration.iconUrl);
  const firstLetter = (integration.name ?? "?")[0].toUpperCase();

  return (
    <View style={{ alignItems: "center", gap: spacing.md }}>
      <View
        className="items-center justify-center overflow-hidden bg-white/[0.07]"
        style={{ width: 80, height: 80, borderRadius: 40 }}
      >
        {logoUri ? (
          <Image
            source={{ uri: logoUri }}
            style={{ width: 54, height: 54 }}
            contentFit="contain"
          />
        ) : (
          <Text className="text-zinc-400" style={{ fontSize: fontSize["2xl"] }}>
            {firstLetter}
          </Text>
        )}
      </View>

      <Text
        className="text-center text-zinc-100"
        style={{ fontSize: fontSize["2xl"], fontWeight: "700" }}
      >
        {integration.name}
      </Text>

      <IntegrationStatusPill status={integration.status} />

      <View
        style={{
          flexDirection: "row",
          flexWrap: "wrap",
          gap: spacing.sm,
          justifyContent: "center",
        }}
      >
        <Badge
          label={getCategoryLabel(integration.category)}
          color="#a1a1aa"
          bg="rgba(255,255,255,0.07)"
        />
        {authType !== "none" ? (
          <Badge
            label={getAuthTypeLabel(authType)}
            color="#00bbff"
            bg="rgba(0,187,255,0.1)"
          />
        ) : null}
        {managedBy && managedBy !== "self" ? (
          <Badge
            label={getManagedByLabel(managedBy)}
            color="#c084fc"
            bg="rgba(192,132,252,0.1)"
          />
        ) : null}
        {isCustom ? (
          <Badge label="Custom" color="#f59e0b" bg="rgba(245,158,11,0.1)" />
        ) : null}
      </View>
    </View>
  );
}
