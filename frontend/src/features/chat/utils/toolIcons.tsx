import Image from "next/image";

import { InformationCircleIcon, NotificationIcon } from "@/icons";
import {
  Brain02Icon,
  CheckmarkCircle02Icon,
  ConnectIcon,
  FileEmpty02Icon,
  Image02Icon,
  SourceCodeCircleIcon,
  Target02Icon,
} from "@/icons";

import { useIconColorDetection } from "../hooks/useIconColorDetection";

interface IconProps {
  size?: number;
  width?: number;
  height?: number;
  strokeWidth?: number;
  className?: string;
  showBackground?: boolean;
}

interface IconConfig {
  icon: React.ComponentType<IconProps> | string;
  bgColor: string;
  iconColor: string;
  isImage?: boolean;
}

/**
 * Normalize a category/integration name for icon lookup
 * - Converts to lowercase
 * - Replaces spaces, dashes, and multiple underscores with single underscore
 */
const normalizeCategoryName = (name: string): string => {
  return name
    .toLowerCase()
    .trim()
    .replace(/[\s\-]+/g, "_") // Replace spaces and dashes with underscore
    .replace(/_+/g, "_") // Replace multiple underscores with single underscore
    .replace(/^_|_$/g, ""); // Remove leading/trailing underscores
};

// Alias mapping for backwards compatibility and category-to-integration mapping
const iconAliases: Record<string, string> = {
  calendar: "google_calendar", // Map old category name to integration name
};

const iconConfigs: Record<string, IconConfig> = {
  gmail: {
    icon: "/images/icons/gmail.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zin`c-200",
    isImage: true,
  },
  productivity: {
    icon: CheckmarkCircle02Icon,
    bgColor: "bg-emerald-500/20 backdrop-blur",
    iconColor: "text-emerald-400",
  },
  documents: {
    icon: FileEmpty02Icon,
    bgColor: "bg-orange-500/20 backdrop-blur",
    iconColor: "text-[#FF4500]",
  },
  google_docs: {
    icon: "/images/icons/google_docs.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  googlesheets: {
    icon: "/images/icons/googlesheets.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  development: {
    icon: SourceCodeCircleIcon,
    bgColor: "bg-cyan-500/20 backdrop-blur",
    iconColor: "text-cyan-400",
  },
  search: {
    icon: "/images/icons/google.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  memory: {
    icon: Brain02Icon,
    bgColor: "bg-indigo-500/20 backdrop-blur",
    iconColor: "text-indigo-400",
  },
  creative: {
    icon: Image02Icon,
    bgColor: "bg-pink-500/20 backdrop-blur",
    iconColor: "text-pink-400",
  },
  weather: {
    icon: "/images/icons/weather.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  goal_tracking: {
    icon: Target02Icon,
    bgColor: "bg-emerald-500/20 backdrop-blur",
    iconColor: "text-emerald-400",
  },
  notion: {
    icon: "/images/icons/notion.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  twitter: {
    icon: "/images/icons/twitter.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  linkedin: {
    icon: "/images/icons/linkedin.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  notifications: {
    icon: NotificationIcon,
    bgColor: "bg-yellow-500/20 backdrop-blur",
    iconColor: "text-yellow-400",
  },
  webpage: {
    icon: InformationCircleIcon,
    bgColor: "bg-purple-500/20 backdrop-blur",
    iconColor: "text-purple-400",
  },
  support: {
    icon: InformationCircleIcon,
    bgColor: "bg-blue-500/20 backdrop-blur",
    iconColor: "text-blue-400",
  },
  general: {
    icon: InformationCircleIcon,
    bgColor: "bg-gray-500/20 backdrop-blur",
    iconColor: "text-gray-400",
  },
  // Integration icons
  google_calendar: {
    icon: "/images/icons/googlecalendar.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  github: {
    icon: "/images/icons/github.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  reddit: {
    icon: "/images/icons/reddit.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  airtable: {
    icon: "/images/icons/airtable.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  linear: {
    icon: "/images/icons/linear.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  slack: {
    icon: "/images/icons/slack.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  hubspot: {
    icon: "/images/icons/hubspot.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  googletasks: {
    icon: "/images/icons/googletasks.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  todoist: {
    icon: "/images/icons/todoist.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  microsoft_teams: {
    icon: "/images/icons/microsoft_teams.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  googlemeet: {
    icon: "/images/icons/googlemeet.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  zoom: {
    icon: "/images/icons/zoom.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  google_maps: {
    icon: "/images/icons/google_maps.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  asana: {
    icon: "/images/icons/asana.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  trello: {
    icon: "/images/icons/trello.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  instagram: {
    icon: "/images/icons/instagram.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  clickup: {
    icon: "/images/icons/clickup.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  integrations: {
    isImage: false,
    icon: ConnectIcon,
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
  },
};

// Component that auto-detects and inverts dark icons
const AutoInvertIcon: React.FC<{
  src: string;
  alt: string;
  size?: number;
  width?: number;
  height?: number;
  className?: string;
}> = ({ src, alt, size, width, height, className }) => {
  const { shouldInvert } = useIconColorDetection(src);

  return (
    <Image
      alt={alt}
      width={width || size || 20}
      height={height || size || 20}
      className={`${className} aspect-square object-contain ${shouldInvert ? "invert" : ""}`}
      src={src}
    />
  );
};

export const getToolCategoryIcon = (
  category: string,
  iconProps: IconProps = {},
) => {
  const { showBackground = true, ...restProps } = iconProps;

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

  // Return with or without background based on showBackground prop
  return showBackground ? (
    <div className={`rounded-lg p-1 ${config.bgColor}`}>{iconElement}</div>
  ) : (
    iconElement
  );
};
