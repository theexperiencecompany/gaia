/**
 * Tool icons — single shared path via `@gaia/shared/icons/tool-icon-config`.
 *
 * Contract:
 * - ALL tool/category -> icon resolution goes through `getToolIconConfig` from shared.
 *   That module owns `toolIconConfigs`, `iconAliases`, `normalizeCategoryName`, colors, isImage flags.
 *   Mobile does NOT duplicate that map — web and mobile share the same source (libs/shared/ts/src/icons).
 * - Image-based integrations: when the API provides `iconUrl` it wins; otherwise fall back to
 *   `INTEGRATION_LOGOS` which itself is derived from shared `getMobileIntegrationLogoUrl` + `INTEGRATION_LOGO_FILES`,
 *   so the artwork stays byte-for-byte identical to web's `getIconPath()`.
 * - Rendering is the ONLY platform branch (expo-image / react-native-svg vs next/image) — business logic stays shared.
 * - Pulsating background and sizing are unified via `wrapWithBackground` so there's a single call-site for bg color + animation.
 *
 * @see libs/shared/ts/src/icons/tool-icon-config.ts
 * @see apps/web/src/features/chat/utils/toolIcons.tsx
 */

import { getToolIconConfig, type ToolIconConfig } from "@gaia/shared/icons";
import { getGaiaIcon, ToolsIcon } from "@icons";
import { Image } from "expo-image";
import type React from "react";
import { useEffect, useRef } from "react";
import { Animated, View } from "react-native";
import { INTEGRATION_LOGOS } from "@/features/integrations/constants/logos";

export type { ToolIconConfig };

function PulsatingBackground({
  bgColorRaw,
  pulsating,
}: {
  bgColorRaw: string;
  pulsating: boolean;
}) {
  const opacity = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (!pulsating) {
      opacity.setValue(1);
      return;
    }

    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 0.4,
          duration: 1000,
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 0.8,
          duration: 1000,
          useNativeDriver: true,
        }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [pulsating, opacity]);

  return (
    <Animated.View
      style={{
        ...absoluteFill,
        backgroundColor: bgColorRaw,
        borderRadius: 8,
        opacity,
      }}
    />
  );
}

const absoluteFill = {
  position: "absolute" as const,
  top: 0,
  left: 0,
  right: 0,
  bottom: 0,
};

export interface ToolIconProps {
  size?: number;
  showBackground?: boolean;
  pulsating?: boolean;
  iconUrl?: string | null;
}

/**
 * Single helper — all icon render paths funnel through here so bg + pulsation
 * stay consistent and the only variance is the resolved icon element + its bgColorRaw.
 */
function wrapWithBackground(
  iconElement: React.ReactElement,
  bgColorRaw: string,
  pulsating: boolean,
  showBackground: boolean,
): React.ReactElement {
  if (!showBackground) return iconElement;
  return (
    <View style={{ padding: 4, position: "relative" }}>
      <PulsatingBackground bgColorRaw={bgColorRaw} pulsating={pulsating} />
      <View style={{ position: "relative" }}>{iconElement}</View>
    </View>
  );
}

export function getToolCategoryIcon(
  category: string,
  iconProps: ToolIconProps = {},
  iconUrl?: string | null,
): React.ReactElement | null {
  const { size = 16, showBackground = true, pulsating = false } = iconProps;

  // Single shared resolution — every branch below reads from this one config lookup.
  const config = getToolIconConfig(category);

  // Image-based fallback is itself shared-derived (INTEGRATION_LOGOS → getMobileIntegrationLogoUrl).
  const integrationLogoFallback =
    config?.isImage && config.icon ? INTEGRATION_LOGOS[config.icon] : undefined;

  const resolvedIconUrl =
    iconProps.iconUrl ?? iconUrl ?? integrationLogoFallback;

  // No config: if caller supplied a raw URL, render it; otherwise no icon (don't invent a local map).
  if (!config) {
    if (resolvedIconUrl) {
      return wrapWithBackground(
        <Image
          source={{ uri: resolvedIconUrl }}
          style={{ width: size, height: size }}
          contentFit="contain"
        />,
        "#3f3f46",
        pulsating,
        showBackground,
      );
    }
    return null;
  }

  // Image-based tool (isImage=true): prefers resolvedIconUrl, falls back to generic ToolsIcon in shared color.
  if (config.isImage) {
    if (resolvedIconUrl) {
      return wrapWithBackground(
        <Image
          source={{ uri: resolvedIconUrl }}
          style={{ width: size, height: size }}
          contentFit="contain"
        />,
        config.bgColorRaw,
        pulsating,
        showBackground,
      );
    }

    const FallbackIcon = ToolsIcon;
    return wrapWithBackground(
      <FallbackIcon size={size} color={config.iconColorRaw} />,
      config.bgColorRaw,
      pulsating,
      showBackground,
    );
  }

  // Component-based tool: resolve via gaia-icons registry (shared icon name → RN component).
  const IconComponent = getGaiaIcon(config.icon) || ToolsIcon;
  return wrapWithBackground(
    <IconComponent size={size} color={config.iconColorRaw} />,
    config.bgColorRaw,
    pulsating,
    showBackground,
  );
}
