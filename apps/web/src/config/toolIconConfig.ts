/**
 * Shared tool icon configuration used by both:
 * - React components (toolIcons.tsx)
 * - OG image generation (api/og routes)
 *
 * Keep icon paths and colors in sync by maintaining this single source of truth.
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
  /** SVG path data for OG image rendering (viewBox assumes 24x24) */
  svgPath?: string;
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
    .replace(/^_|_$/g, "");
}

/** Alias mapping for backwards compatibility and category-to-integration mapping */
export const iconAliases: Record<string, string> = {
  calendar: "google_calendar",
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
  google_docs: {
    icon: "/images/icons/google_docs.webp",
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
  google_calendar: {
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

  // Category icons (non-image, use React components in toolIcons.tsx)
  // SVG paths are included for OG image rendering (viewBox: 0 0 24 24)
  todos: {
    icon: "CheckListIcon",
    bgColor: "bg-emerald-500/20 backdrop-blur",
    iconColor: "text-emerald-400",
    bgColorRaw: "rgba(16, 185, 129, 0.2)",
    iconColorRaw: "#34d399",
    isImage: false,
    svgPath: "M11 3.99998H6.8C5.11984 3.99998 4.27976 3.99998 3.63803 4.32696C3.07354 4.6146 2.6146 5.07353 2.32698 5.63801C2 6.27975 2 7.11983 2 8.79998V17.2C2 18.8801 2 19.7202 2.32698 20.362C2.6146 20.9264 3.07354 21.3854 3.63803 21.673C4.27976 22 5.11984 22 6.8 22H15.2C16.8802 22 17.7202 22 18.362 21.673C18.9265 21.3854 19.3854 20.9264 19.673 20.362C20 19.7202 20 18.8801 20 17.2V13M7.5 11.5L10.5 14.5L22 3",
  },
  reminders: {
    icon: "AlarmClockIcon",
    bgColor: "bg-blue-500/20 backdrop-blur",
    iconColor: "text-blue-400",
    bgColorRaw: "rgba(59, 130, 246, 0.2)",
    iconColorRaw: "#60a5fa",
    isImage: false,
    svgPath: "M5 3L2 6M22 6L19 3M6 19L4 21M18 19L20 21M12 9V13L14 15M12 21C15.866 21 19 17.866 19 14C19 10.134 15.866 7 12 7C8.13401 7 5 10.134 5 14C5 17.866 8.13401 21 12 21Z",
  },
  documents: {
    icon: "FileEmpty02Icon",
    bgColor: "bg-orange-500/20 backdrop-blur",
    iconColor: "text-[#FF4500]",
    bgColorRaw: "rgba(249, 115, 22, 0.2)",
    iconColorRaw: "#fb923c",
    isImage: false,
    svgPath: "M14 2.26953V6.4C14 6.96005 14 7.24008 14.109 7.45399C14.2049 7.64215 14.3578 7.79513 14.546 7.89101C14.7599 8 15.0399 8 15.6 8H19.7305M14 17H8M16 13H8M20 9.98822V17.2C20 18.8802 20 19.7202 19.673 20.362C19.3854 20.9265 18.9265 21.3854 18.362 21.673C17.7202 22 16.8802 22 15.2 22H8.8C7.11984 22 6.27976 22 5.63803 21.673C5.07354 21.3854 4.6146 20.9265 4.32698 20.362C4 19.7202 4 18.8802 4 17.2V6.8C4 5.11984 4 4.27976 4.32698 3.63803C4.6146 3.07354 5.07354 2.6146 5.63803 2.32698C6.27976 2 7.11984 2 8.8 2H12.0118C12.7455 2 13.1124 2 13.4577 2.08289C13.7638 2.15638 14.0564 2.27759 14.3249 2.44208C14.6276 2.6276 14.887 2.88703 15.4059 3.40589L18.5941 6.59411C19.113 7.11297 19.3724 7.3724 19.5579 7.67515C19.7224 7.94356 19.8436 8.2362 19.9171 8.5423C20 8.88757 20 9.25445 20 9.98822Z",
  },
  development: {
    icon: "SourceCodeCircleIcon",
    bgColor: "bg-cyan-500/20 backdrop-blur",
    iconColor: "text-cyan-400",
    bgColorRaw: "rgba(6, 182, 212, 0.2)",
    iconColorRaw: "#22d3ee",
    isImage: false,
    svgPath: "M14.5 15L17.5 12L14.5 9M9.5 9L6.5 12L9.5 15M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 17.5228 6.47715 22 12 22Z",
  },
  memory: {
    icon: "Brain02Icon",
    bgColor: "bg-indigo-500/20 backdrop-blur",
    iconColor: "text-indigo-400",
    bgColorRaw: "rgba(99, 102, 241, 0.2)",
    iconColorRaw: "#818cf8",
    isImage: false,
    svgPath: "M12 2C10.0605 2 8.3306 2.9441 7.2122 4.39986C5.27969 3.63055 3.11168 4.67229 2.50453 6.67098C1.80336 8.98239 3.14541 11.4234 5.4001 12.2894C5.08654 13.1596 4.83618 14.0603 4.65216 14.984C4.34562 16.5244 4.19235 17.2946 4.54839 17.8729C4.95551 18.5339 5.87973 18.7744 6.5762 18.3903C6.04386 19.0661 5.68178 19.8762 5.54977 20.7683C5.40935 21.717 6.08718 22.5859 7.04366 22.6919C7.89746 22.7867 8.71858 22.2417 8.93597 21.4096C9.05689 20.946 9.26215 20.4894 9.48698 20.1002C9.78169 19.5898 10.2328 19.0927 10.6803 18.7056C11.0296 18.4034 11.4219 18.0836 12 17.8M12 2C13.9395 2 15.6694 2.9441 16.7878 4.39986C18.7203 3.63055 20.8883 4.67229 21.4955 6.67098C22.1966 8.98239 20.8546 11.4234 18.5999 12.2894C18.9135 13.1596 19.1638 14.0603 19.3478 14.984C19.6544 16.5244 19.8076 17.2946 19.4516 17.8729C19.0445 18.5339 18.1203 18.7744 17.4238 18.3903C17.9561 19.0661 18.3182 19.8762 18.4502 20.7683C18.5907 21.717 17.9128 22.5859 16.9563 22.6919C16.1025 22.7867 15.2814 22.2417 15.064 21.4096C14.9431 20.946 14.7379 20.4894 14.513 20.1002C14.2183 19.5898 13.7672 19.0927 13.3197 18.7056C12.9704 18.4034 12.5781 18.0836 12 17.8M12 2V17.8",
  },
  creative: {
    icon: "Image02Icon",
    bgColor: "bg-pink-500/20 backdrop-blur",
    iconColor: "text-pink-400",
    bgColorRaw: "rgba(236, 72, 153, 0.2)",
    iconColorRaw: "#f472b6",
    isImage: false,
    svgPath: "M2 12.6564L7.1377 8.68247C8.05623 7.9887 9.38133 8.05203 10.2264 8.82988L15 13M10.5 8C10.5 8.82843 9.82843 9.5 9 9.5C8.17157 9.5 7.5 8.82843 7.5 8C7.5 7.17157 8.17157 6.5 9 6.5C9.82843 6.5 10.5 7.17157 10.5 8ZM22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12C2 6.47715 6.47715 2 12 2C17.5228 2 22 6.47715 22 12Z",
  },
  goal_tracking: {
    icon: "Target02Icon",
    bgColor: "bg-emerald-500/20 backdrop-blur",
    iconColor: "text-emerald-400",
    bgColorRaw: "rgba(16, 185, 129, 0.2)",
    iconColorRaw: "#34d399",
    isImage: false,
    svgPath: "M12 12V12.01M16 12C16 14.2091 14.2091 16 12 16C9.79086 16 8 14.2091 8 12C8 9.79086 9.79086 8 12 8C14.2091 8 16 9.79086 16 12ZM22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12C2 6.47715 6.47715 2 12 2C17.5228 2 22 6.47715 22 12Z",
  },
  notifications: {
    icon: "NotificationIcon",
    bgColor: "bg-yellow-500/20 backdrop-blur",
    iconColor: "text-yellow-400",
    bgColorRaw: "rgba(234, 179, 8, 0.2)",
    iconColorRaw: "#facc15",
    isImage: false,
    svgPath: "M9.35419 21C10.0593 21.6224 10.9856 22 12 22C13.0144 22 13.9407 21.6224 14.6458 21M18 8C18 6.4087 17.3679 4.88258 16.2426 3.75736C15.1174 2.63214 13.5913 2 12 2C10.4087 2 8.88258 2.63214 7.75736 3.75736C6.63214 4.88258 6 6.4087 6 8C6 11.0902 5.22047 13.206 4.34966 14.6054C3.61513 15.7859 3.24787 16.3761 3.26132 16.5408C3.27624 16.7231 3.31486 16.7926 3.46178 16.9016C3.59446 17 4.19259 17 5.38885 17H18.6112C19.8074 17 20.4056 17 20.5382 16.9016C20.6851 16.7926 20.7238 16.7231 20.7387 16.5408C20.7521 16.3761 20.3849 15.7859 19.6503 14.6054C18.7795 13.206 18 11.0902 18 8Z",
  },
  webpage: {
    icon: "InformationCircleIcon",
    bgColor: "bg-purple-500/20 backdrop-blur",
    iconColor: "text-purple-400",
    bgColorRaw: "rgba(168, 85, 247, 0.2)",
    iconColorRaw: "#c084fc",
    isImage: false,
    svgPath: "M12 16V12M12 8H12.01M22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12C2 6.47715 6.47715 2 12 2C17.5228 2 22 6.47715 22 12Z",
  },
  support: {
    icon: "InformationCircleIcon",
    bgColor: "bg-blue-500/20 backdrop-blur",
    iconColor: "text-blue-400",
    bgColorRaw: "rgba(59, 130, 246, 0.2)",
    iconColorRaw: "#60a5fa",
    isImage: false,
    svgPath: "M12 16V12M12 8H12.01M22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12C2 6.47715 6.47715 2 12 2C17.5228 2 22 6.47715 22 12Z",
  },
  general: {
    icon: "ToolsIcon",
    bgColor: "bg-gray-500/20 backdrop-blur",
    iconColor: "text-gray-400",
    bgColorRaw: "rgba(113, 113, 122, 0.2)",
    iconColorRaw: "#a1a1aa",
    isImage: false,
    svgPath: "M10.0503 10.0503L3.53553 3.53553M12.5 2V4M12.5 4V6M12.5 4H14.5M12.5 4H10.5M20.5 12H22.5M20.5 12H18.5M20.5 12V14M20.5 12V10M14.1213 14.1213L20.2929 20.2929C20.6834 20.6834 20.6834 21.3166 20.2929 21.7071L19.7071 22.2929C19.3166 22.6834 18.6834 22.6834 18.2929 22.2929L5.70711 9.70711C5.31658 9.31658 5.31658 8.68342 5.70711 8.29289L8.29289 5.70711C8.68342 5.31658 9.31658 5.31658 9.70711 5.70711L14.1213 10.1213M14.1213 14.1213L14.1213 10.1213M14.1213 14.1213L10.1213 14.1213M14.1213 10.1213L10.1213 10.1213M10.1213 10.1213L10.1213 14.1213",
  },
  integrations: {
    icon: "ConnectIcon",
    bgColor: "bg-zinc-700",
    iconColor: "text-zinc-200",
    bgColorRaw: "#3f3f46",
    iconColorRaw: "#e4e4e7",
    isImage: false,
    svgPath: "M10 17.6586V20C10 21.1046 10.8954 22 12 22C13.1046 22 14 21.1046 14 20V17.6586M10 6.34141V4C10 2.89543 10.8954 2 12 2C13.1046 2 14 2.89543 14 4V6.34141M17.6569 14H20C21.1046 14 22 13.1046 22 12C22 10.8954 21.1046 10 20 10H17.6569M6.34315 10H4C2.89543 10 2 10.8954 2 12C2 13.1046 2.89543 14 4 14H6.34315M7.75736 16.2426C5.41421 13.8995 5.41421 10.1005 7.75736 7.75736C10.1005 5.41421 13.8995 5.41421 16.2426 7.75736C18.5858 10.1005 18.5858 13.8995 16.2426 16.2426C13.8995 18.5858 10.1005 18.5858 7.75736 16.2426Z",
  },
  handoff: {
    icon: "SquareArrowUpRight02Icon",
    bgColor: "bg-sky-500/20 backdrop-blur",
    iconColor: "text-sky-400",
    bgColorRaw: "rgba(14, 165, 233, 0.2)",
    iconColorRaw: "#38bdf8",
    isImage: false,
    svgPath: "M11 4H7.8C6.11984 4 5.27976 4 4.63803 4.32698C4.07354 4.6146 3.6146 5.07354 3.32698 5.63803C3 6.27976 3 7.11984 3 8.8V16.2C3 17.8802 3 18.7202 3.32698 19.362C3.6146 19.9265 4.07354 20.3854 4.63803 20.673C5.27976 21 6.11984 21 7.8 21H15.2C16.8802 21 17.7202 21 18.362 20.673C18.9265 20.3854 19.3854 19.9265 19.673 19.362C20 18.7202 20 17.8802 20 16.2V13M15 3H21M21 3V9M21 3L12 12",
  },
  retrieve_tools: {
    icon: "PackageOpenIcon",
    bgColor: "bg-indigo-500/20 backdrop-blur",
    iconColor: "text-indigo-400",
    bgColorRaw: "rgba(99, 102, 241, 0.2)",
    iconColorRaw: "#818cf8",
    isImage: false,
    svgPath: "M20.5 7.27777L12 12M12 12L3.5 7.27777M12 12V21.5M21 16.0586V7.94137C21 7.5918 21 7.41702 20.9495 7.25869C20.9049 7.11878 20.8318 6.98997 20.7354 6.88058C20.6263 6.75778 20.4766 6.66702 20.1772 6.4855L12.7772 2.0855C12.4934 1.91345 12.3515 1.82742 12.2015 1.79427C12.0685 1.76484 11.9315 1.76484 11.7985 1.79427C11.6485 1.82742 11.5066 1.91345 11.2228 2.0855L3.82284 6.4855C3.52342 6.66702 3.37372 6.75778 3.26458 6.88058C3.16815 6.98997 3.09512 7.11878 3.05048 7.25869C3 7.41702 3 7.5918 3 7.94137V16.0586C3 16.4082 3 16.583 3.05048 16.7413C3.09512 16.8812 3.16815 17.01 3.26458 17.1194C3.37372 17.2422 3.52342 17.333 3.82284 17.5145L11.2228 21.9145C11.5066 22.0866 11.6485 22.1726 11.7985 22.2057C11.9315 22.2352 12.0685 22.2352 12.2015 22.2057C12.3515 22.1726 12.4934 22.0866 12.7772 21.9145L20.1772 17.5145C20.4766 17.333 20.6263 17.2422 20.7354 17.1194C20.8318 17.01 20.9049 16.8812 20.9495 16.7413C21 16.583 21 16.4082 21 16.0586Z",
  },
  executor: {
    icon: "ComputerTerminal01Icon",
    bgColor: "bg-teal-500/20 backdrop-blur",
    iconColor: "text-teal-400",
    bgColorRaw: "rgba(20, 184, 166, 0.2)",
    iconColorRaw: "#2dd4bf",
    isImage: false,
    svgPath: "M4 17L10 11L4 5M12 19H20",
  },
  unknown: {
    icon: "ToolsIcon",
    bgColor: "bg-zinc-500/20 backdrop-blur",
    iconColor: "text-zinc-400",
    bgColorRaw: "rgba(113, 113, 122, 0.2)",
    iconColorRaw: "#a1a1aa",
    isImage: false,
    svgPath: "M12 16V12M12 8H12.01M22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12C2 6.47715 6.47715 2 12 2C17.5228 2 22 6.47715 22 12Z",
  },
};

/**
 * Get icon config for a category, with normalization and alias resolution
 */
export function getToolIconConfig(
  category: string
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
      ([key]) => normalizeCategoryName(key) === finalCategory
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
 * OG image generation (Satori) doesn't support WebP, so we map to PNG/SVG alternatives
 */
const webpToOgFormat: Record<string, string> = {
  "/images/icons/google_docs.webp": "/images/icons/google_docs.webp", // No alternative, will fallback
  "/images/icons/googlesheets.webp": "/images/icons/googlesheets.webp", // No alternative, will fallback
  "/images/icons/weather.webp": "/images/icons/weather.webp", // No alternative, will fallback
  "/images/icons/notion.webp": "/images/icons/notion.webp", // No alternative, will fallback
  "/images/icons/twitter.webp": "/images/icons/x.svg", // Use X logo
  "/images/icons/googlecalendar.webp": "/images/icons/googlemeet.svg", // Use similar Google icon
  "/images/icons/deepwiki.webp": "/images/icons/deepwiki.webp", // No alternative, will fallback
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
