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
    <Image
      alt={`${category} Icon`}
      {...defaultProps}
      className={`${restProps.className} aspect-square object-contain`}
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
