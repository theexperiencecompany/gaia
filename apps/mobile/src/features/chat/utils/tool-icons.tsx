import { getToolIconConfig, type ToolIconConfig } from "@gaia/shared/icons";
import { getGaiaIcon, ToolsIcon } from "@icons";
import type React from "react";
import { useEffect, useRef } from "react";
import { Animated, Image, View } from "react-native";

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

export function getToolCategoryIcon(
  category: string,
  iconProps: ToolIconProps = {},
  iconUrl?: string | null,
): React.ReactElement | null {
  const { size = 16, showBackground = true, pulsating = false } = iconProps;

  const resolvedIconUrl = iconProps.iconUrl ?? iconUrl;

  const config = getToolIconConfig(category);

  if (!config) {
    if (resolvedIconUrl) {
      const iconElement = (
        <Image
          source={{ uri: resolvedIconUrl }}
          style={{ width: size, height: size }}
          resizeMode="contain"
        />
      );
      if (!showBackground) return iconElement;
      return (
        <View style={{ padding: 4, position: "relative" }}>
          <PulsatingBackground bgColorRaw="#3f3f46" pulsating={pulsating} />
          <View style={{ position: "relative" }}>{iconElement}</View>
        </View>
      );
    }
    return null;
  }

  if (config.isImage) {
    if (resolvedIconUrl) {
      const iconElement = (
        <Image
          source={{ uri: resolvedIconUrl }}
          style={{ width: size, height: size }}
          resizeMode="contain"
        />
      );
      if (!showBackground) return iconElement;
      return (
        <View style={{ padding: 4, position: "relative" }}>
          <PulsatingBackground
            bgColorRaw={config.bgColorRaw}
            pulsating={pulsating}
          />
          <View style={{ position: "relative" }}>{iconElement}</View>
        </View>
      );
    }

    const FallbackIcon = ToolsIcon;
    const fallbackElement = (
      <FallbackIcon size={size} color={config.iconColorRaw} />
    );
    if (!showBackground) return fallbackElement;
    return (
      <View style={{ padding: 4, position: "relative" }}>
        <PulsatingBackground
          bgColorRaw={config.bgColorRaw}
          pulsating={pulsating}
        />
        <View style={{ position: "relative" }}>{fallbackElement}</View>
      </View>
    );
  }

  const IconComponent = getGaiaIcon(config.icon) || ToolsIcon;
  const iconElement = <IconComponent size={size} color={config.iconColorRaw} />;

  if (!showBackground) return iconElement;

  return (
    <View style={{ padding: 4, position: "relative" }}>
      <PulsatingBackground
        bgColorRaw={config.bgColorRaw}
        pulsating={pulsating}
      />
      <View style={{ position: "relative" }}>{iconElement}</View>
    </View>
  );
}
