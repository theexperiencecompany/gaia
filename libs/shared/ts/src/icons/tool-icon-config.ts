/**
 * Tool Icon Configuration - Shared Source of Truth
 *
 * React-free config used by web (Next.js), mobile (React Native), and Edge
 * runtime (OG image generation). Each platform handles icon rendering itself.
 *
 * For image-based icons: `icon` is a key name (e.g. "gmail") — platforms
 * resolve the actual URL or asset from it.
 * For component-based icons: `icon` is the gaia-icons component name.
 */

export interface ToolIconConfig {
  /** Gaia icon component name, or key name for image-based icons */
  icon: string;
  /** Tailwind background color class */
  bgColor: string;
  /** Tailwind text color class */
  iconColor: string;
  /** Raw background color for React Native and OG images */
  bgColorRaw: string;
  /** Raw icon color for React Native and OG images */
  iconColorRaw: string;
  /** Whether this uses an image vs a gaia-icons component */
  isImage: boolean;
}

export function normalizeCategoryName(name: string): string {
  if (!name) return "general";
  return name
    .toLowerCase()
    .trim()
    .replace(/[\s-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/(?:^_|_$)/g, "");
}

export const iconAliases: Record<string, string> = {
  calendar: "googlecalendar",
  planner: "plan_tasks",
};

export const toolIconConfigs: Record<string, ToolIconConfig> = {
  // Image-based integrations
  gmail: {
    icon: "gmail",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  googledocs: {
    icon: "googledocs",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  googlesheets: {
    icon: "googlesheets",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  search: {
    icon: "search",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  weather: {
    icon: "weather",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  notion: {
    icon: "notion",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  twitter: {
    icon: "twitter",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  linkedin: {
    icon: "linkedin",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  googlecalendar: {
    icon: "googlecalendar",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  github: {
    icon: "github",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  reddit: {
    icon: "reddit",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  airtable: {
    icon: "airtable",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  linear: {
    icon: "linear",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  slack: {
    icon: "slack",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  hubspot: {
    icon: "hubspot",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  googletasks: {
    icon: "googletasks",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  todoist: {
    icon: "todoist",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  microsoft_teams: {
    icon: "microsoft_teams",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  googlemeet: {
    icon: "googlemeet",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  zoom: {
    icon: "zoom",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  google_maps: {
    icon: "google_maps",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  asana: {
    icon: "asana",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  trello: {
    icon: "trello",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  instagram: {
    icon: "instagram",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  clickup: {
    icon: "clickup",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  deepwiki: {
    icon: "deepwiki",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  context7: {
    icon: "context7",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  hackernews: {
    icon: "hackernews",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  instacart: {
    icon: "instacart",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  yelp: {
    icon: "yelp",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  vercel: {
    icon: "vercel",
    bgColor: "bg-zinc-800",
    iconColor: "text-white",
    bgColorRaw: "#27272a",
    iconColorRaw: "#ffffff",
    isImage: true,
  },
  perplexity: {
    icon: "perplexity",
    bgColor: "bg-zinc-800",
    iconColor: "text-white",
    bgColorRaw: "#27272a",
    iconColorRaw: "#ffffff",
    isImage: true,
  },
  figma: {
    icon: "figma",
    bgColor: "bg-zinc-800",
    iconColor: "text-white",
    bgColorRaw: "#27272a",
    iconColorRaw: "#ffffff",
    isImage: true,
  },
  browserbase: {
    icon: "browserbase",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  posthog: {
    icon: "posthog",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  agentmail: {
    icon: "agentmail",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },
  gaia: {
    icon: "gaia",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: true,
  },

  // Category icons — use gaia-icons component names
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
  spawn_subagent: {
    icon: "WorkflowCircle06Icon",
    bgColor: "bg-violet-500/20 backdrop-blur",
    iconColor: "text-violet-400",
    bgColorRaw: "rgba(139, 92, 246, 0.2)",
    iconColorRaw: "#a78bfa",
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
  fileSystem: {
    icon: "FolderFileStorageIcon",
    bgColor: "bg-fuchsia-500/20 backdrop-blur",
    iconColor: "text-fuchsia-400",
    bgColorRaw: "rgba(217, 70, 239, 0.2)",
    iconColorRaw: "#e879f9",
    isImage: false,
  },
  skills: {
    icon: "BodyPartMuscleIcon",
    bgColor: "bg-rose-500/20 backdrop-blur",
    iconColor: "text-rose-400",
    bgColorRaw: "rgba(244, 63, 94, 0.2)",
    iconColorRaw: "#fb7185",
    isImage: false,
  },
  context: {
    icon: "PuzzleIcon",
    bgColor: "bg-lime-500/20 backdrop-blur",
    iconColor: "text-lime-400",
    bgColorRaw: "rgba(132, 204, 22, 0.2)",
    iconColorRaw: "#a3e635",
    isImage: false,
  },
  plan_tasks: {
    icon: "TaskDailyIcon",
    bgColor: "bg-violet-500/20 backdrop-blur",
    iconColor: "text-violet-400",
    bgColorRaw: "rgba(139, 92, 246, 0.2)",
    iconColorRaw: "#a78bfa",
    isImage: false,
  },
  workflows: {
    icon: "ZapIcon",
    bgColor: "bg-yellow-500/20 backdrop-blur",
    iconColor: "text-yellow-400",
    bgColorRaw: "rgba(234, 179, 8, 0.2)",
    iconColorRaw: "#facc15",
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
    const matchingConfig = Object.entries(toolIconConfigs).find(
      ([key]) => normalizeCategoryName(key) === finalCategory,
    );
    if (matchingConfig) config = matchingConfig[1];
  }

  return config;
}

export function getCategoryInitial(category: string): string {
  const name = category.replace(/_/g, " ");
  return name.charAt(0).toUpperCase();
}
