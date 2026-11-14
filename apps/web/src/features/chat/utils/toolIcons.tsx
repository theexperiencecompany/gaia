/**
 * Tool Icons - React UI Layer
 *
 * This file provides React components for rendering tool/category icons.
 * It imports configuration from toolIconConfig.ts (the single source of truth)
 * and maps icon names to actual React components.
 *
 * For OG images (Edge runtime), see: iconPaths.generated.ts
 * For icon configuration: src/config/toolIconConfig.ts
 */

import {
  AiWebBrowsingIcon,
  AlarmClockIcon,
  AppStoreIcon,
  BodyPartMuscleIcon,
  BookBookmark02Icon,
  BookOpen01Icon,
  Brain02Icon,
  Camera01Icon,
  CancelCircleHalfDotIcon,
  CheckListIcon,
  CheckmarkCircle02Icon,
  ClipboardIcon,
  Clock04Icon,
  ComputerIcon,
  ComputerTerminal01Icon,
  ConnectIcon,
  Copy01Icon,
  CreditCardIcon,
  FileEmpty02Icon,
  FolderFileStorageIcon,
  Globe02Icon,
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
  UserAccountIcon,
  WindowsNewIcon,
  WorkflowCircle06Icon,
  ZapIcon,
} from "@icons";
import {
  getIconPath,
  iconAliases,
  normalizeCategoryName,
  toolIconConfigs,
} from "@/config/toolIconConfig";
import { AutoInvertIcon } from "./AutoInvertIcon";

interface IconProps {
  size?: number;
  width?: number;
  height?: number;
  strokeWidth?: number;
  className?: string;
  showBackground?: boolean;
  iconOnly?: boolean; // When true, renders just the icon without background wrapper
  pulsating?: boolean; // When true, animates the background with a pulsating effect
}

interface IconConfig {
  icon: React.ComponentType<IconProps> | string;
  bgColor: string;
  iconColor: string;
  isImage?: boolean;
}

const isRenderableIconSrc = (src: string): boolean => {
  if (!src) return false;
  const normalizedSrc = src.trim().toLowerCase();
  return (
    normalizedSrc.startsWith("/") ||
    normalizedSrc.startsWith("http://") ||
    normalizedSrc.startsWith("https://") ||
    normalizedSrc.startsWith("data:image/") ||
    normalizedSrc.startsWith("blob:")
  );
};

/** Map icon component names to actual React components */
const iconComponentMap: Record<string, React.ComponentType<IconProps>> = {
  AiWebBrowsingIcon,
  CheckListIcon,
  Clock04Icon,
  CheckmarkCircle02Icon,
  ClipboardIcon,
  CancelCircleHalfDotIcon,
  AlarmClockIcon,
  AppStoreIcon,
  BookBookmark02Icon,
  BookOpen01Icon,
  Camera01Icon,
  ComputerIcon,
  Copy01Icon,
  CreditCardIcon,
  Globe02Icon,
  PuzzleIcon,
  WindowsNewIcon,
  FileEmpty02Icon,
  SourceCodeCircleIcon,
  Brain02Icon,
  Image02Icon,
  Target02Icon,
  NotificationIcon,
  InformationCircleIcon,
  ToolsIcon,
  UserAccountIcon,
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

/** Build runtime icon configs from shared config */
const iconConfigs: Record<string, IconConfig> = Object.fromEntries(
  Object.entries(toolIconConfigs).map(([key, config]) => {
    if (config.isImage) {
      const resolvedImagePath = getIconPath(key);
      const hasValidImagePath =
        !!resolvedImagePath && isRenderableIconSrc(resolvedImagePath);

      return [
        key,
        {
          icon: hasValidImagePath ? resolvedImagePath : ToolsIcon,
          bgColor: config.bgColor,
          iconColor: config.iconColor,
          isImage: hasValidImagePath,
        },
      ];
    }

    return [
      key,
      {
        icon: iconComponentMap[config.icon] || ToolsIcon,
        bgColor: config.bgColor,
        iconColor: config.iconColor,
        isImage: false,
      },
    ];
  }),
);

export const getToolCategoryIcon = (
  category: string,
  iconProps: IconProps = {},
  iconUrl?: string | null,
) => {
  const {
    showBackground = true,
    iconOnly = false,
    pulsating = false,
    ...restProps
  } = iconProps;

  const defaultProps = {
    size: restProps.size || 16,
    width: restProps.width || 20,
    height: restProps.height || 20,
    strokeWidth: restProps.strokeWidth || 0,
    className: restProps.className,
  };

  // The card's own integration icon from the server wins; the category glyph is the fallback.
  if (iconUrl && isRenderableIconSrc(iconUrl)) {
    const iconElement = (
      <AutoInvertIcon
        alt={`${category} Icon`}
        size={defaultProps.size}
        width={defaultProps.width}
        height={defaultProps.height}
        className={restProps.className}
        src={iconUrl}
      />
    );
    return showBackground ? (
      <div className="relative rounded-lg p-1">
        <div
          className={`absolute inset-0 rounded-lg bg-zinc-700 ${pulsating ? "animate-pulse" : ""}`}
        />
        <div className="relative">{iconElement}</div>
      </div>
    ) : (
      iconElement
    );
  }

  // Normalize the input category name
  const normalizedCategory = normalizeCategoryName(category);

  // Resolve aliases first (e.g., 'calendar' -> 'googlecalendar')
  const aliasedCategory =
    iconAliases[normalizedCategory] ||
    iconAliases[category] ||
    normalizedCategory;

  // Normalize the aliased category as well
  const finalCategory = normalizeCategoryName(aliasedCategory);

  // Try to find config with normalized key
  let config = iconConfigs[finalCategory];

  // If not found, try searching through all configs with normalized keys
  if (!config) {
    const normalizedConfigs = Object.entries(iconConfigs);
    const matchingConfig = normalizedConfigs.find(
      ([key]) => normalizeCategoryName(key) === finalCategory,
    );
    if (matchingConfig) {
      config = matchingConfig[1];
    }
  }

  if (!config) return null;

  const iconElement = config.isImage ? (
    <AutoInvertIcon
      alt={`${category} Icon`}
      size={defaultProps.size}
      width={defaultProps.width}
      height={defaultProps.height}
      className={restProps.className}
      src={config.icon as string}
    />
  ) : (
    (() => {
      const IconComponent = config.icon as React.ComponentType<IconProps>;
      return (
        <IconComponent
          {...defaultProps}
          className={restProps.className || config.iconColor}
        />
      );
    })()
  );

  // Return with or without background based on showBackground and iconOnly props
  // iconOnly: when true, image icons skip background for minimal display (e.g., loading messages)
  const shouldShowBackground = showBackground && !(iconOnly && config.isImage);
  return shouldShowBackground ? (
    <div className="relative rounded-lg p-1">
      <div
        className={`absolute inset-0 rounded-lg ${config.bgColor} ${
          pulsating ? "animate-pulse" : ""
        }`}
      />
      <div className="relative">{iconElement}</div>
    </div>
  ) : (
    iconElement
  );
};
