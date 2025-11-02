import {
  BookOpen,
  CircleArrowUp,
  FileText,
  HelpCircle,
  Home,
  Lightbulb,
  LogOut,
  Mail,
  MessageSquare,
  Pencil,
  Plus,
  Shield,
  Star,
  Trash2,
  TrendingUp,
  Workflow,
  ZapIcon,
} from "lucide-react";
import { ReactNode } from "react";

import {
  AiSearch02Icon,
  BookOpen02Icon,
  Brain02Icon,
  BubbleChatQuestionIcon,
  CalendarAdd01Icon,
  CalendarIcon,
  CheckmarkCircle02Icon,
  CheckmarkSquare03Icon,
  CustomerService01Icon,
  DiscordIcon,
  FlowchartIcon1,
  Home01Icon,
  LabelImportantIcon,
  MessageMultiple02Icon,
  MoneyBag02Icon,
  NewsIcon,
  NotificationIcon,
  PencilEdit01Icon,
  PencilRenameIcon,
  Sent02Icon,
  Settings01Icon,
  SquareLock02Icon,
  Target04Icon,
  WhatsappIcon,
} from "@/components/shared/icons";

// Menu item configuration
export interface MenuItemConfig {
  id: string;
  label: string;
  icon: ReactNode;
  path?: string; // For navigation items
  action?: string; // For action items (handled in component)
  shortcut?: string;
  externalUrl?: string; // For external links
  requiresAuth?: boolean;
  hideWhenSubscribed?: boolean; // For upgrade CTA
}

export type MenuSection = "actions" | "chat_actions" | "pages" | "user";

export interface MenuSectionConfig {
  key: MenuSection;
  heading?: string;
  items: MenuItemConfig[];
}

// Page navigation items
export const PAGE_ITEMS: MenuItemConfig[] = [
  {
    id: "home",
    label: "Home Page",
    icon: <Home01Icon width={18} height={18} color={undefined} />,
    path: "/",
  },
  {
    id: "notifications",
    label: "Notifications",
    icon: <NotificationIcon width={18} height={18} color={undefined} />,
    path: "/notifications",
  },
  {
    id: "calendar",
    label: "Calendar",
    icon: <CalendarIcon width={18} height={18} color={undefined} />,
    path: "/calendar",
  },
  {
    id: "goals",
    label: "Goals",
    icon: <Target04Icon width={18} height={18} color={undefined} />,
    path: "/goals",
  },
  {
    id: "todos",
    label: "Todos",
    icon: <CheckmarkCircle02Icon width={18} height={18} color={undefined} />,
    path: "/todos",
  },
  {
    id: "workflows",
    label: "Workflows",
    icon: <ZapIcon width={18} height={18} color={undefined} />,
    path: "/workflows",
  },
  {
    id: "chats",
    label: "Chats",
    icon: <MessageMultiple02Icon width={18} height={18} color={undefined} />,
    path: "/c",
  },
  {
    id: "use_cases",
    label: "Use Cases",
    icon: <Lightbulb width={18} height={18} color={undefined} />,
    externalUrl: "https://heygaia.io/use-cases",
  },
  {
    id: "pricing",
    label: "Pricing Page",
    icon: <MoneyBag02Icon width={18} height={18} color={undefined} />,
    path: "/pricing",
  },
];

// Chat actions
export const CHAT_ACTIONS: MenuItemConfig[] = [
  {
    id: "star_chat",
    label: "Star Chat",
    icon: <Star width={18} height={18} color={undefined} />,
    action: "star_chat",
    requiresAuth: true,
  },
  {
    id: "rename_chat",
    label: "Rename Chat",
    icon: <PencilRenameIcon width={18} height={18} color={undefined} />,
    action: "rename_chat",
    requiresAuth: true,
  },
  {
    id: "delete_chat",
    label: "Delete Chat",
    icon: <Trash2 width={18} height={18} color="rgb(244 63 94)" />,
    action: "delete_chat",
    requiresAuth: true,
  },
];

// Quick actions
export const ACTION_ITEMS: MenuItemConfig[] = [
  {
    id: "new_chat",
    label: "New Chat",
    icon: <PencilEdit01Icon width={18} height={18} color={undefined} />,
    action: "new_chat",
  },
  {
    id: "create_calendar_event",
    label: "Create Calendar Event",
    icon: <CalendarAdd01Icon width={18} height={18} color={undefined} />,
    action: "create_calendar_event",
    requiresAuth: true,
  },
  {
    id: "send_email",
    label: "Send Email",
    icon: <Sent02Icon width={18} height={18} color={undefined} />,
    action: "send_email",
    requiresAuth: true,
  },
  {
    id: "create_workflow",
    label: "Create Workflow",
    icon: <FlowchartIcon1 width={18} height={18} color={undefined} />,
    action: "create_workflow",
    requiresAuth: true,
  },
  {
    id: "create_goal",
    label: "Create Goal",
    icon: <Target04Icon width={18} height={18} color={undefined} />,
    action: "create_goal",
    requiresAuth: true,
  },
  {
    id: "create_todo",
    label: "Create Todo",
    icon: <CheckmarkSquare03Icon width={18} height={18} color={undefined} />,
    action: "create_todo",
    requiresAuth: true,
  },
  {
    id: "upgrade_to_pro",
    label: "Upgrade to Pro",
    icon: <CircleArrowUp width={18} height={18} color="#00bbff" />,
    path: "/pricing",
    hideWhenSubscribed: true,
  },
];

// User settings and community
export const USER_ITEMS: MenuItemConfig[] = [
  {
    id: "memories",
    label: "Memories",
    icon: <Brain02Icon width={18} height={18} color={undefined} />,
    path: "/settings?section=memory",
  },
  {
    id: "send_feedback",
    label: "Send Feedback",
    icon: <MessageSquare width={18} height={18} color={undefined} />,
    action: "send_feedback",
  },
  {
    id: "help",
    label: "Help",
    icon: <HelpCircle width={18} height={18} color={undefined} />,
    action: "help",
  },
  {
    id: "documentation",
    label: "Documentation",
    icon: <BookOpen02Icon width={18} height={18} color={undefined} />,
    externalUrl: "https://docs.heygaia.io",
  },
  {
    id: "gaia_status",
    label: "GAIA Status",
    icon: <AiSearch02Icon width={18} height={18} color={undefined} />,
    externalUrl: "https://status.heygaia.io",
  },
  {
    id: "terms",
    label: "Terms of Service",
    icon: <FileText width={18} height={18} color={undefined} />,
    path: "/terms",
  },
  {
    id: "privacy",
    label: "Privacy Policy",
    icon: <Shield width={18} height={18} color={undefined} />,
    path: "/privacy",
  },
  {
    id: "support",
    label: "Create Support Request",
    icon: <CustomerService01Icon width={18} height={18} color={undefined} />,
    action: "create_support",
  },
  {
    id: "discord",
    label: "Join Discord",
    icon: <DiscordIcon width={18} height={18} color="#5865F2" />,
    externalUrl: "discord",
  },
  {
    id: "whatsapp",
    label: "WhatsApp Community",
    icon: <WhatsappIcon width={18} height={18} color="#25d366" />,
    externalUrl: "whatsapp",
  },
  {
    id: "log_out",
    label: "Log Out",
    icon: <LogOut width={18} height={18} color="rgb(244 63 94)" />,
    action: "log_out",
    requiresAuth: true,
  },
  {
    id: "settings",
    label: "Settings",
    icon: <Settings01Icon width={18} height={18} color={undefined} />,
    path: "/settings",
    shortcut: "⌘,",
  },
];

// Menu sections configuration
export const MENU_SECTIONS: MenuSectionConfig[] = [
  {
    key: "actions",
    heading: "Quick Actions",
    items: ACTION_ITEMS,
  },
  {
    key: "chat_actions",
    heading: "Chat Actions",
    items: CHAT_ACTIONS,
  },
  {
    key: "pages",
    heading: "Pages",
    items: PAGE_ITEMS,
  },
  {
    key: "user",
    heading: "User & Community",
    items: USER_ITEMS,
  },
];

// Animation variants
export const ANIMATION_CONFIG = {
  backdrop: {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    transition: {
      duration: 0.2,
      ease: [0.19, 1, 0.22, 1] as [number, number, number, number],
    },
  },
  container: {
    initial: { opacity: 0, scale: 0.95, y: -8 },
    animate: { opacity: 1, scale: 1, y: 0 },
    exit: { opacity: 0, scale: 0.95, y: -8 },
    transition: {
      duration: 0.2,
      ease: [0.19, 1, 0.22, 1] as [number, number, number, number],
    },
  },
} as const;

// Styling constants
export const COMMAND_MENU_STYLES = {
  backdrop: "fixed inset-0 bg-black/40 backdrop-blur-md",
  container:
    "relative w-full max-w-2xl overflow-hidden rounded-2xl border border-zinc-800/40 bg-zinc-900/50 backdrop-blur-2xl shadow-2xl",
  inputWrapper:
    "flex items-center gap-3 border-b border-zinc-800/30 px-5 py-4 mb-2",
  searchIcon: "h-4 w-4 text-zinc-500",
  input:
    "flex-1 bg-transparent  text-zinc-100 placeholder-zinc-500 outline-none",
  list: "max-h-[400px] overflow-y-auto pb-3 outline-none!",
  empty: "flex h-16 items-center justify-center text-sm text-zinc-500",
  item: "mx-2 flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-3 text-sm text-zinc-500 transition-all duration-200 hover:bg-zinc-800/40 aria-selected:bg-zinc-800/50 aria-selected:text-zinc-300!",
  separator: "mx-3 h-px bg-zinc-800/50",
  itemShortcut:
    "inline-flex h-5 items-center gap-0.5 rounded-md bg-zinc-800/50 px-1.5 font-mono text-[10px] font-medium text-zinc-500",
  flexOne: "flex-1",
  contentWrapper: "min-w-0 flex-1",
  resultTitle: "truncate text-sm",
  resultSubtitle: "truncate text-xs text-zinc-500",
  resultTitleClamp: "line-clamp-1 truncate text-sm",
  footer: "border-t border-zinc-800/30 px-5 py-3",
  footerText: "text-xs text-zinc-500",
  modalWrapper: "fixed inset-0 z-50 flex items-start justify-center pt-[20vh]",
  shortcutText: "text-xs",
  groupHeadings:
    "[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pt-5 [&_[cmdk-group-heading]]:pb-2 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-zinc-500",
} as const;
