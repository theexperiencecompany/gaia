import { Image } from "expo-image";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { getIntegrationLogo } from "../constants/logos";
import type { Integration } from "../types";

interface IntegrationLogoProps {
  integration: Pick<Integration, "id" | "name" | "iconUrl">;
  size: number;
  borderRadius?: number;
}

/**
 * Circular logo with deterministic fallback initial when no logo is known.
 */
export function IntegrationLogo({
  integration,
  size,
  borderRadius,
}: IntegrationLogoProps) {
  const radius = borderRadius ?? Math.round(size / 2);
  const logoUri = getIntegrationLogo(integration.id, integration.iconUrl);
  const initial = (integration.name ?? "?").charAt(0).toUpperCase();

  // Hue derived from the integration ID so the fallback colour is stable.
  const hue =
    integration.id.split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0) %
    360;

  if (logoUri) {
    return (
      <View
        className="items-center justify-center bg-white/[0.05]"
        style={{
          width: size,
          height: size,
          borderRadius: radius,
          overflow: "hidden",
        }}
      >
        <Image
          source={{ uri: logoUri }}
          style={{ width: size - 12, height: size - 12 }}
          contentFit="contain"
        />
      </View>
    );
  }

  return (
    <View
      className="items-center justify-center"
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        backgroundColor: `hsla(${hue},55%,38%,0.3)`,
        borderWidth: 1,
        borderColor: `hsla(${hue},55%,55%,0.2)`,
      }}
    >
      <Text
        style={{
          fontSize: Math.round(size * 0.38),
          fontWeight: "700",
          color: `hsl(${hue},70%,80%)`,
        }}
      >
        {initial}
      </Text>
    </View>
  );
}
