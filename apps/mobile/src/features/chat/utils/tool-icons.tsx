import type { ToolIconConfig } from "@gaia/shared/icons";
import {
  iconAliases,
  normalizeCategoryName,
  toolIconConfigs,
} from "@gaia/shared/icons";
import {
  AlarmClockIcon,
  BodyPartMuscleIcon,
  Brain02Icon,
  CheckListIcon,
  ComputerTerminal01Icon,
  ConnectIcon,
  FileEmpty02Icon,
  FolderFileStorageIcon,
  Image02Icon,
  InformationCircleIcon,
  NotificationIcon,
  PackageOpenIcon,
  PuzzleIcon,
  SourceCodeCircleIcon,
  SquareArrowUpRight02Icon,
  Target02Icon,
  TaskDailyIcon,
  ToolsIcon,
  WorkflowCircle06Icon,
  ZapIcon,
} from "@icons";
import type React from "react";
import { useEffect, useRef } from "react";
import { Animated, Image, View } from "react-native";

export type { ToolIconConfig };

const iconComponentMap: Record<
  string,
  React.ComponentType<{ size?: number; color?: string }>
> = {
  CheckListIcon,
  AlarmClockIcon,
  PuzzleIcon,
  FileEmpty02Icon,
  SourceCodeCircleIcon,
  Brain02Icon,
  Image02Icon,
  Target02Icon,
  NotificationIcon,
  InformationCircleIcon,
  ToolsIcon,
  ConnectIcon,
  SquareArrowUpRight02Icon,
  PackageOpenIcon,
  ComputerTerminal01Icon,
  FolderFileStorageIcon,
  BodyPartMuscleIcon,
  WorkflowCircle06Icon,
  TaskDailyIcon,
  ZapIcon,
};

function getToolIconConfig(category: string): ToolIconConfig | undefined {
  const normalizedCategory = normalizeCategoryName(category);
  const aliasedCategory =
    iconAliases[normalizedCategory] ||
    iconAliases[category] ||
    normalizedCategory;
  const finalCategory = normalizeCategoryName(aliasedCategory);

  let config = toolIconConfigs[finalCategory];

  if (!config) {
    const matchingConfig = Object.entries(toolIconConfigs).find(
      ([key]) => normalizeCategoryName(key) === finalCategory,
    );
    if (matchingConfig) config = matchingConfig[1];
  }

  return config;
}

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

    const FallbackIcon = iconComponentMap.ToolsIcon || ToolsIcon;
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

  const IconComponent =
    iconComponentMap[config.icon] || iconComponentMap.ToolsIcon;
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
