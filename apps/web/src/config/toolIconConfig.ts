/**
 * Tool Icon Configuration - Single Source of Truth
 *
 * This file defines icon mappings, colors, and aliases for all tool categories.
 * It is intentionally React-free to support Edge runtime (OG image generation).
 *
 * ARCHITECTURE:
 * ┌─────────────────────────────────────────────────────────────────────┐
 * │  toolIconConfig.ts (this file)                                      │
 * │  - Category → icon name (string, e.g., "Brain02Icon")               │
 * │  - Tailwind classes (bgColor, iconColor)                            │
 * │  - Raw CSS colors (bgColorRaw, iconColorRaw) for Satori             │
 * │  - Image paths for platform integrations                            │
 * │  - Aliases and normalization utilities                              │
 * └──────────────────────┬──────────────────────────────────────────────┘
 *                        │
 *          ┌─────────────┴─────────────┐
 *          ▼                           ▼
 *  ┌───────────────────┐     ┌────────────────────────┐
 *  │  toolIcons.tsx    │     │  iconPaths.generated.ts│
 *  │  (React UI)       │     │  (OG images/Edge)      │
 *  │                   │     │                        │
 *  │  Maps icon names  │     │  Pre-extracted SVG     │
 *  │  to components    │     │  paths from gaia-icons │
 *  └───────────────────┘     └────────────────────────┘
 *
 * WHY THIS SEPARATION?
 * - OG routes run on Edge runtime which cannot import React components
 * - Satori needs raw SVG paths and CSS colors, not Tailwind classes
 * - This file stays React-free to be safely imported anywhere
 */

export interface ToolIconConfig {
  /** Icon path for image-based icons, or component name for React icons */
  icon: string;
  /** Tailwind background color class */
  bgColor: string;
  /** Tailwind text color class */
  iconColor: string;
  /** Raw background color for OG images (CSS value) */
  bgColorRaw: string;
  /** Raw icon/text color for OG images (CSS value) */
  iconColorRaw: string;
  /** Whether this uses an image file vs a React icon component */
  isImage: boolean;
}

/**
 * Normalize a category/integration name for icon lookup
 */
export function normalizeCategoryName(name: string): string {
  if (!name) return "general";
  return name
    .toLowerCase()
    .trim()
    .replace(/[\s-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/(?:^_|_$)/g, "");
}

/** Alias mapping for backwards compatibility and category-to-integration mapping */
export const iconAliases: Record<string, string> = {
  calendar: "googlecalendar",
};

/** Tool icon configurations - single source of truth */
export const toolIconConfigs: Record<string, ToolIconConfig> = {
  // Image-based integrations
  gmail: {
    icon: "/images/icons/gmail.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  googledocs: {
    icon: "/images/icons/googledocs.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  googlesheets: {
    icon: "/images/icons/googlesheets.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  search: {
    icon: "/images/icons/google.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  weather: {
    icon: "/images/icons/weather.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  notion: {
    icon: "/images/icons/notion.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  twitter: {
    icon: "/images/icons/twitter.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  linkedin: {
    icon: "/images/icons/linkedin.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  googlecalendar: {
    icon: "/images/icons/googlecalendar.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  github: {
    icon: "/images/icons/github.png",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  reddit: {
    icon: "/images/icons/reddit.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  airtable: {
    icon: "/images/icons/airtable.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  linear: {
    icon: "/images/icons/linear.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  slack: {
    icon: "/images/icons/slack.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  hubspot: {
    icon: "/images/icons/hubspot.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  googletasks: {
    icon: "/images/icons/googletasks.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  todoist: {
    icon: "/images/icons/todoist.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  microsoft_teams: {
    icon: "/images/icons/microsoft_teams.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  googlemeet: {
    icon: "/images/icons/googlemeet.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  zoom: {
    icon: "/images/icons/zoom.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  google_maps: {
    icon: "/images/icons/google_maps.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  asana: {
    icon: "/images/icons/asana.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  trello: {
    icon: "/images/icons/trello.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  instagram: {
    icon: "/images/icons/instagram.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  clickup: {
    icon: "/images/icons/clickup.svg",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  deepwiki: {
    icon: "/images/icons/deepwiki.webp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  context7: {
    icon: "/images/icons/context7.png",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  hackernews: {
    icon: "/images/icons/hackernews.png",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  instacart: {
    icon: "/images/icons/instacart.png",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  yelp: {
    icon: "/images/icons/yelp.png",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  vercel: {
    icon: "/images/icons/vercel.svg",
    bgColor: "bg-zinc-800",
    iconColor: "text-white",
    bgColorRaw: "#27272a",
    iconColorRaw: "#ffffff",
    isImage: true,
  },
  perplexity: {
    icon: "/images/icons/perplexity.png",
    bgColor: "bg-zinc-800",
    iconColor: "text-white",
    bgColorRaw: "#27272a",
    iconColorRaw: "#ffffff",
    isImage: true,
  },
  figma: {
    icon: "/images/icons/figma.svg",
    bgColor: "bg-zinc-800",
    iconColor: "text-white",
    bgColorRaw: "#27272a",
    iconColorRaw: "#ffffff",
    isImage: true,
  },
  browserbase: {
    icon: "https://www.google.com/s2/favicons?domain=browserbase.com&sz=128",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  posthog: {
    icon: "https://www.google.com/s2/favicons?domain=posthog.com&sz=128",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  agentmail: {
    icon: "https://t0.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=http://agentmail.to&size=256",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },

  // Category icons (non-image, use React components in toolIcons.tsx)
  // OG images use auto-generated paths from iconPaths.generated.ts via icon name
  todos: {
    icon: "CheckListIcon",
    bgColor: "bg-emerald-500/20 backdrop-blur",
    iconColor: "text-emerald-400",
    bgColorRaw: "rgba(16, 185, 129, 0.2)",
    iconColorRaw: "#34d399",
    isImage: false,
  },
  reminders: {
    icon: "AlarmClockIcon",
    bgColor: "bg-blue-500/20 backdrop-blur",
    iconColor: "text-blue-400",
    bgColorRaw: "rgba(59, 130, 246, 0.2)",
    iconColorRaw: "#60a5fa",
    isImage: false,
  },
  documents: {
    icon: "FileEmpty02Icon",
    bgColor: "bg-orange-500/20 backdrop-blur",
    iconColor: "text-[#FF4500]",
    bgColorRaw: "rgba(249, 115, 22, 0.2)",
    iconColorRaw: "#fb923c",
    isImage: false,
  },
  development: {
    icon: "SourceCodeCircleIcon",
    bgColor: "bg-cyan-500/20 backdrop-blur",
    iconColor: "text-cyan-400",
    bgColorRaw: "rgba(6, 182, 212, 0.2)",
    iconColorRaw: "#22d3ee",
    isImage: false,
  },
  memory: {
    icon: "Brain02Icon",
    bgColor: "bg-indigo-500/20 backdrop-blur",
    iconColor: "text-indigo-400",
    bgColorRaw: "rgba(99, 102, 241, 0.2)",
    iconColorRaw: "#818cf8",
    isImage: false,
  },
  creative: {
    icon: "Image02Icon",
    bgColor: "bg-pink-500/20 backdrop-blur",
    iconColor: "text-pink-400",
    bgColorRaw: "rgba(236, 72, 153, 0.2)",
    iconColorRaw: "#f472b6",
    isImage: false,
  },
  goal_tracking: {
    icon: "Target02Icon",
    bgColor: "bg-emerald-500/20 backdrop-blur",
    iconColor: "text-emerald-400",
    bgColorRaw: "rgba(16, 185, 129, 0.2)",
    iconColorRaw: "#34d399",
    isImage: false,
  },
  notifications: {
    icon: "NotificationIcon",
    bgColor: "bg-yellow-500/20 backdrop-blur",
    iconColor: "text-yellow-400",
    bgColorRaw: "rgba(234, 179, 8, 0.2)",
    iconColorRaw: "#facc15",
    isImage: false,
  },
  webpage: {
    icon: "InformationCircleIcon",
    bgColor: "bg-purple-500/20 backdrop-blur",
    iconColor: "text-purple-400",
    bgColorRaw: "rgba(168, 85, 247, 0.2)",
    iconColorRaw: "#c084fc",
    isImage: false,
  },
  support: {
    icon: "InformationCircleIcon",
    bgColor: "bg-blue-500/20 backdrop-blur",
    iconColor: "text-blue-400",
    bgColorRaw: "rgba(59, 130, 246, 0.2)",
    iconColorRaw: "#60a5fa",
    isImage: false,
  },
  general: {
    icon: "ToolsIcon",
    bgColor: "bg-gray-500/20 backdrop-blur",
    iconColor: "text-gray-400",
    bgColorRaw: "rgba(113, 113, 122, 0.2)",
    iconColorRaw: "#a1a1aa",
    isImage: false,
  },
  integrations: {
    icon: "ConnectIcon",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: false,
  },
  handoff: {
    icon: "SquareArrowUpRight02Icon",
    bgColor: "bg-sky-500/20 backdrop-blur",
    iconColor: "text-sky-400",
    bgColorRaw: "rgba(14, 165, 233, 0.2)",
    iconColorRaw: "#38bdf8",
    isImage: false,
  },
  retrieve_tools: {
    icon: "PackageOpenIcon",
    bgColor: "bg-indigo-500/20 backdrop-blur",
    iconColor: "text-indigo-400",
    bgColorRaw: "rgba(99, 102, 241, 0.2)",
    iconColorRaw: "#818cf8",
    isImage: false,
  },
  executor: {
    icon: "ComputerTerminal01Icon",
    bgColor: "bg-teal-500/20 backdrop-blur",
    iconColor: "text-teal-400",
    bgColorRaw: "rgba(20, 184, 166, 0.2)",
    iconColorRaw: "#2dd4bf",
    isImage: false,
  },
  unknown: {
    icon: "ToolsIcon",
    bgColor: "bg-zinc-500/20 backdrop-blur",
    iconColor: "text-zinc-400",
    bgColorRaw: "rgba(113, 113, 122, 0.2)",
    iconColorRaw: "#a1a1aa",
    isImage: false,
  },
};

/**
 * Get icon config for a category, with normalization and alias resolution
 */
export function getToolIconConfig(
  category: string,
): ToolIconConfig | undefined {
  const normalizedCategory = normalizeCategoryName(category);
  const aliasedCategory =
    iconAliases[normalizedCategory] ||
    iconAliases[category] ||
    normalizedCategory;
  const finalCategory = normalizeCategoryName(aliasedCategory);

  let config = toolIconConfigs[finalCategory];

  if (!config) {
    const normalizedConfigs = Object.entries(toolIconConfigs);
    const matchingConfig = normalizedConfigs.find(
      ([key]) => normalizeCategoryName(key) === finalCategory,
    );
    if (matchingConfig) {
      config = matchingConfig[1];
    }
  }

  return config;
}

/**
 * Get the icon path for image-based icons
 */
export function getIconPath(category: string): string | null {
  const config = getToolIconConfig(category);
  return config?.isImage ? config.icon : null;
}

/**
 * WebP to OG-compatible format mapping
 * OG image generation (Satori) doesn't support WebP, so we map to PNG/SVG alternatives.
 * WebP icons not listed here will return null from getOgIconPath(), triggering a fallback icon.
 */
const webpToOgFormat: Record<string, string> = {
  "/images/icons/twitter.webp": "/images/icons/x.svg",
};

/**
 * Get an OG-compatible icon path (converts WebP to PNG/SVG when available)
 * Satori (OG image generator) doesn't support WebP images
 */
export function getOgIconPath(category: string): string | null {
  const config = getToolIconConfig(category);
  if (!config?.isImage) return null;

  const iconPath = config.icon;

  // If it's a WebP, check if we have an alternative
  if (iconPath.endsWith(".webp")) {
    const alternative = webpToOgFormat[iconPath];
    // If alternative is still webp or doesn't exist, return null to trigger fallback
    if (!alternative || alternative.endsWith(".webp")) {
      return null;
    }
    return alternative;
  }

  return iconPath;
}

/**
 * Get category initial for fallback display
 */
export function getCategoryInitial(category: string): string {
  const name = category.replace(/_/g, " ");
  return name.charAt(0).toUpperCase();
}
