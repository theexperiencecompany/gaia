import Image from "next/image";
import {
  AlarmClockIcon,
  Brain02Icon,
  CheckListIcon,
  ComputerTerminal01Icon,
  ConnectIcon,
  FileEmpty02Icon,
  Image02Icon,
  InformationCircleIcon,
  NotificationIcon,
  PackageOpenIcon,
  SourceCodeCircleIcon,
  SquareArrowUpRight02Icon,
  Target02Icon,
  ToolsIcon,
} from "@/icons";
import {
  toolIconConfigs,
  iconAliases,
  normalizeCategoryName,
} from "@/config/toolIconConfig";

interface IconProps {
  size?: number;
  width?: number;
  height?: number;
  strokeWidth?: number;
  className?: string;
  showBackground?: boolean;
  iconOnly?: boolean; // When true, renders just the icon without background wrapper
}

interface IconConfig {
  icon: React.ComponentType<IconProps> | string;
  bgColor: string;
  iconColor: string;
  isImage?: boolean;
}

/** Map icon component names to actual React components */
const iconComponentMap: Record<string, React.ComponentType<IconProps>> = {
  CheckListIcon,
  AlarmClockIcon,
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
};

/** Build runtime icon configs from shared config */
const iconConfigs: Record<string, IconConfig> = Object.fromEntries(
  Object.entries(toolIconConfigs).map(([key, config]) => [
    key,
    {
      icon: config.isImage
        ? config.icon
        : iconComponentMap[config.icon] || ToolsIcon,
      bgColor: config.bgColor,
      iconColor: config.iconColor,
      isImage: config.isImage,
    },
  ])
);

// Component that auto-detects and inverts dark icons
const AutoInvertIcon: React.FC<{
  src: string;
  alt: string;
  size?: number;
  width?: number;
  height?: number;
  className?: string;
}> = ({ src, alt, size, width, height, className }) => {
  // const { shouldInvert } = useIconColorDetection(src);

  return (
    <Image
      alt={alt}
      width={width || size || 20}
      height={height || size || 20}
      className={`${className} aspect-square object-contain`}
      src={src}
    />
    //  ${shouldInvert ? "invert" : ""} commented out temporarily
  );
};

export const getToolCategoryIcon = (
  category: string,
  iconProps: IconProps = {},
  iconUrl?: string | null
) => {
  const { showBackground = true, iconOnly = false, ...restProps } = iconProps;

  const defaultProps = {
    size: restProps.size || 16,
    width: restProps.width || 20,
    height: restProps.height || 20,
    strokeWidth: restProps.strokeWidth || 0,
    className: restProps.className,
  };

  // Normalize the input category name
  const normalizedCategory = normalizeCategoryName(category);

  // Resolve aliases first (e.g., 'calendar' -> 'google_calendar')
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
      ([key]) => normalizeCategoryName(key) === finalCategory
    );
    if (matchingConfig) {
      config = matchingConfig[1];
    }
  }

  // If no predefined config found, try iconUrl fallback for custom integrations
  if (!config) {
    if (iconUrl) {
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
        <div className="rounded-lg p-1 bg-zinc-700">{iconElement}</div>
      ) : (
        iconElement
      );
    }
    return null;
  }

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
    <div className={`rounded-lg p-1 ${config.bgColor}`}>{iconElement}</div>
  ) : (
    iconElement
  );
};
