import { Bell, Info } from "lucide-react";
import Image from "next/image";

import {
  Brain02Icon,
  CheckmarkCircle02Icon,
  FileEmpty02Icon,
  Image02Icon,
  SourceCodeCircleIcon,
  Target02Icon,
} from "@/components/shared/icons";

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

const iconConfigs: Record<string, IconConfig> = {
  gmail: {
    icon: "/images/icons/gmail.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  calendar: {
    icon: "/images/icons/googlecalendar.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
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
    iconColor: "text-orange-400",
  },
  google_docs: {
    icon: "/images/icons/google_docs.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    isImage: true,
  },
  google_sheets: {
    icon: "/images/icons/google_sheets.webp",
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
    icon: Bell,
    bgColor: "bg-yellow-500/20 backdrop-blur",
    iconColor: "text-yellow-400",
  },
  webpage: {
    icon: Info,
    bgColor: "bg-purple-500/20 backdrop-blur",
    iconColor: "text-purple-400",
  },
  support: {
    icon: Info,
    bgColor: "bg-blue-500/20 backdrop-blur",
    iconColor: "text-blue-400",
  },
  general: {
    icon: Info,
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
  google_tasks: {
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
  google_meet: {
    icon: "/images/icons/google_meet.svg",
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
    strokeWidth: restProps.strokeWidth || 2,
    className: restProps.className,
  };

  const config = iconConfigs[category];
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
