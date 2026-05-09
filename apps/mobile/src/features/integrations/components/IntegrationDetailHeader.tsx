import { Image } from "expo-image";
import { View } from "react-native";
import { AppIcon, UserCircle02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { getIntegrationLogo } from "../constants/logos";
import type { Integration } from "../types";

interface IntegrationDetailHeaderProps {
  integration: Integration;
}

/**
 * Header for the integration detail sheet.
 *
 * Mirrors the web `IntegrationSidebar` header byte-for-byte:
 *   - 40px logo, no circular background tint, no padding
 *   - Tiny chip row that ONLY shows "Connected" when connected and a
 *     "Created by …" chip for custom integrations (no category, auth-type,
 *     managed-by, or "Custom" badges — those don't exist on web)
 *   - Title in `text-2xl font-semibold text-zinc-100`
 *   - Description directly under the title in `text-sm font-light
 *     text-zinc-400`
 */
export function IntegrationDetailHeader({
  integration,
}: IntegrationDetailHeaderProps) {
  const { fontSize, spacing } = useResponsive();

  const isConnected = integration.status === "connected";
  const isCustom = integration.source === "custom";
  const creator = integration.creator;
  const showCreatorChip = isCustom && !!creator?.name;

  const logoUri = getIntegrationLogo(integration.id, integration.iconUrl);
  const firstLetter = (integration.name ?? "?")[0].toUpperCase();

  return (
    <View style={{ gap: spacing.xs }}>
      {logoUri ? (
        <Image
          source={{ uri: logoUri }}
          style={{ width: 40, height: 40 }}
          contentFit="contain"
        />
      ) : (
        <View
          className="items-center justify-center bg-white/[0.06]"
          style={{ width: 40, height: 40, borderRadius: 8 }}
        >
          <Text className="text-zinc-300" style={{ fontSize: fontSize.lg }}>
            {firstLetter}
          </Text>
        </View>
      )}

      {(isConnected || showCreatorChip) && (
        <View
          style={{
            flexDirection: "row",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 6,
            marginTop: 8,
          }}
        >
          {isConnected ? (
            <View
              style={{
                borderRadius: 6,
                paddingHorizontal: 8,
                paddingVertical: 3,
                backgroundColor: "rgba(34,197,94,0.16)",
              }}
            >
              <Text
                style={{
                  color: "#4ade80",
                  fontSize: fontSize.xs - 1,
                  fontWeight: "500",
                }}
              >
                Connected
              </Text>
            </View>
          ) : null}

          {showCreatorChip ? (
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                borderRadius: 6,
                paddingHorizontal: 8,
                paddingVertical: 3,
                backgroundColor: "rgba(255,255,255,0.06)",
              }}
            >
              {creator?.picture ? (
                <Image
                  source={{ uri: creator.picture }}
                  style={{ width: 14, height: 14, borderRadius: 7 }}
                  contentFit="cover"
                />
              ) : (
                <AppIcon icon={UserCircle02Icon} size={12} color="#a1a1aa" />
              )}
              <Text
                className="text-zinc-400"
                style={{
                  fontSize: fontSize.xs - 1,
                  fontWeight: "300",
                }}
              >
                Created by {creator?.name ?? "Unknown"}
              </Text>
            </View>
          ) : null}
        </View>
      )}

      <Text
        className="text-zinc-100"
        style={{
          fontSize: fontSize["2xl"],
          fontWeight: "600",
          marginTop: 4,
        }}
      >
        {integration.name}
      </Text>
    </View>
  );
}
