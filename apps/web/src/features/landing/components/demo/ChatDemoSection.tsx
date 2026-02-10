"use client";

import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownSection,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Select, SelectItem, SelectSection } from "@heroui/react";
import { AnimatePresence, motion } from "framer-motion";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { BubbleChatSparkIcon } from "@/components/shared/icons";
import { LogoWithContextMenu } from "@/components/shared/LogoWithContextMenu";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import DummyComposer from "@/features/landing/components/demo/DummyComposer";
import EmailComposeCard from "@/features/mail/components/EmailComposeCard";
import {
  AiBrain01Icon,
  ArrowRight01Icon,
  BookOpen02Icon,
  BubbleChatAddIcon,
  Calendar03Icon,
  ChartLineData02Icon,
  CheckListIcon,
  ChevronDown,
  ChevronsDownUp,
  ChevronsUpDown,
  CircleArrowUp02Icon,
  CloudDownloadIcon,
  ConnectIcon,
  CustomerService01Icon,
  DashboardSquare02Icon,
  Delete02Icon,
  DiscordIcon,
  Edit02Icon,
  KeyboardIcon,
  Logout02Icon,
  MessageMultiple02Icon,
  NotificationIcon,
  PinIcon,
  SearchIcon,
  Settings01Icon,
  SidebarLeft01Icon,
  SidebarRight01Icon,
  SparklesIcon,
  Target02Icon,
  TwitterIcon,
  UserCircleIcon,
  WhatsappIcon,
  Wrench01Icon,
  ZapIcon,
} from "@/icons";

// ─── Timing (ms) ─────────────────────────────────────────────────────────────
const T = {
  userMsg: 500,
  thinking: 900,
  fetching: 2000,
  emailing: 3400,
  toolCalls: 4800,
  botResponse: 5300,
  emailCard: 7100,
  done: 8700,
  loop: 13500,
};

const ease = [0.32, 0.72, 0, 1] as const;
const tx = { duration: 0.18, ease };

const slideUp = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -8 },
};

// ─── Static demo data ─────────────────────────────────────────────────────────
const navButtons = [
  { Icon: DashboardSquare02Icon, label: "Dashboard" },
  { Icon: Calendar03Icon, label: "Calendar" },
  { Icon: Target02Icon, label: "Goals" },
  { Icon: CheckListIcon, label: "Todos" },
  { Icon: ConnectIcon, label: "Integrations" },
  { Icon: ZapIcon, label: "Workflows" },
  { Icon: MessageMultiple02Icon, label: "Chats", active: true },
];

const chatGroups = {
  Today: [
    { id: "t1", label: "HN + email digest", active: true },
    { id: "t2", label: "Plan my week" },
  ],
  Yesterday: [
    { id: "t3", label: "Summarize inbox" },
    { id: "t4", label: "Draft blog post" },
  ],
  "Last 30 days": [
    { id: "t5", label: "Book flight tickets" },
    { id: "t6", label: "Weekly retrospective" },
    { id: "t7", label: "Research competitors" },
  ],
};

const demoTools = [
  {
    category: "executor",
    name: "executor",
    message: "Starting task executor",
  },
  {
    category: "retrieve_tools",
    name: "retrieve_tools",
    message: "Retrieving tools",
  },
  {
    category: "web_search",
    name: "fetch_url",
    message: "Fetching Hacker News",
  },
  {
    category: "gmail",
    name: "gmail_create_email_draft",
    message: "Composing email draft",
  },
  {
    category: "handoff",
    name: "handoff",
    message: "Finalising response",
  },
];

const BOT_RESPONSE =
  "I've fetched the top 5 Hacker News stories and composed this email digest for you:";

const DEMO_EMAIL = {
  to: ["aryan@example.com"],
  subject: "Your Hacker News Digest — Top Stories Today",
  body: `Hi Aryan,

Here are today's top Hacker News stories:

1. Show HN: I built an open-source AI assistant (1.2k pts, 312 comments)
2. The future of personal computing (847 pts, 198 comments)
3. Ask HN: How do you manage information overload? (734 pts, 421 comments)
4. Rust is now the third most popular language (612 pts, 87 comments)
5. New research: LLMs can now reason about time (589 pts, 143 comments)

Have a great day!
— GAIA`,
  thread_id: "demo-thread-001",
};

// ─── Wave spinner ─────────────────────────────────────────────────────────────
function MiniWaveSpinner() {
  const delays = [0, 0.12, 0.24, 0.12, 0.24, 0.36, 0.24, 0.36, 0.48];
  return (
    <div className="grid grid-cols-3 gap-0.5 shrink-0">
      {delays.map((d, i) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: static
          key={i}
          className="h-1.5 w-1.5"
          style={{
            backgroundColor: "#00bbff",
            animation: "waveDiagTLAnimation 0.7s ease-out infinite",
            animationDelay: `${d}s`,
          }}
        />
      ))}
    </div>
  );
}

// ─── Tool calls ───────────────────────────────────────────────────────────────
function DemoToolCalls({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={tx}
      className="w-fit max-w-full"
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex cursor-pointer items-center gap-2 py-1 text-zinc-500 transition-colors hover:text-white"
      >
        <div className="flex items-center -space-x-2">
          {demoTools.map((t, i) => (
            <div
              key={t.name}
              className="relative flex h-7 w-7 items-center justify-center"
              style={{ rotate: i % 2 === 0 ? "8deg" : "-8deg", zIndex: i }}
            >
              {getToolCategoryIcon(t.category, { width: 21, height: 21 }) ?? (
                <div className="rounded-lg bg-zinc-800 p-1">
                  <Wrench01Icon width={14} height={14} />
                </div>
              )}
            </div>
          ))}
        </div>
        <span className="text-xs font-medium">
          Used {demoTools.length} tools
        </span>
        <ChevronDown
          className={`${expanded ? "rotate-180" : ""} transition-transform duration-200`}
          width={14}
          height={14}
        />
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="py-1">
              {demoTools.map((t, i) => (
                <div key={t.name} className="flex items-stretch gap-2">
                  <div className="flex flex-col items-center self-stretch">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center">
                      {getToolCategoryIcon(t.category, {
                        size: 20,
                        width: 20,
                        height: 20,
                      }) ?? (
                        <div className="rounded-lg bg-zinc-800 p-1">
                          <Wrench01Icon width={14} height={14} />
                        </div>
                      )}
                    </div>
                    {i < demoTools.length - 1 && (
                      <div className="min-h-3 w-px flex-1 bg-zinc-700" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="pt-1 text-xs font-medium text-zinc-400">
                      {t.message}
                    </p>
                    <p className="text-[11px] capitalize text-zinc-600">
                      {t.category.replace(/_/g, " ")}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ─── Settings dropdown (exact match of real SettingsMenu) ────────────────────
const ic = "h-[18px] w-[18px]";

function DemoSettingsDropdown({
  children,
  onOpenChange,
}: {
  children: React.ReactNode;
  onOpenChange?: (o: boolean) => void;
}) {
  return (
    <Dropdown
      placement="right-end"
      className="dark bg-secondary-bg text-foreground shadow-xl"
      offset={21}
      onOpenChange={onOpenChange}
    >
      <DropdownTrigger>{children}</DropdownTrigger>
      <DropdownMenu aria-label="Settings" variant="faded">
        {/* Upgrade to Pro */}
        <DropdownSection showDivider classNames={{ divider: "bg-zinc-800/60" }}>
          <DropdownItem
            key="upgrade"
            startContent={
              <CircleArrowUp02Icon className={ic} color="#00bbff" />
            }
            classNames={{ title: "text-primary font-medium" }}
          >
            Upgrade to Pro
          </DropdownItem>
        </DropdownSection>

        {/* Settings */}
        <DropdownSection
          title="Settings"
          showDivider
          classNames={{ divider: "bg-zinc-800/60" }}
        >
          <DropdownItem
            key="profile"
            startContent={<SparklesIcon className={ic} />}
            className="text-zinc-400 hover:text-white"
          >
            Profile Card
          </DropdownItem>
          <DropdownItem
            key="account"
            startContent={<UserCircleIcon className={ic} />}
            className="text-zinc-400 hover:text-white"
          >
            Account
          </DropdownItem>
          <DropdownItem
            key="usage"
            startContent={<ChartLineData02Icon className={ic} />}
            className="text-zinc-400 hover:text-white"
          >
            Usage
          </DropdownItem>
          <DropdownItem
            key="preferences"
            startContent={<MessageMultiple02Icon className={ic} />}
            className="text-zinc-400 hover:text-white"
          >
            Preferences
          </DropdownItem>
          <DropdownItem
            key="memory"
            startContent={<AiBrain01Icon className={ic} />}
            className="text-zinc-400 hover:text-white"
          >
            Memories
          </DropdownItem>
          <DropdownItem
            key="shortcuts"
            startContent={<KeyboardIcon className={ic} />}
            className="text-zinc-400 hover:text-white"
          >
            Keyboard Shortcuts
          </DropdownItem>
        </DropdownSection>

        {/* Community */}
        <DropdownSection
          title="Community"
          showDivider
          classNames={{ divider: "bg-zinc-800/60" }}
        >
          <DropdownItem
            key="twitter"
            startContent={<TwitterIcon className={ic} />}
            style={{ color: "#1da1f2" }}
          >
            Follow Us
          </DropdownItem>
          <DropdownItem
            key="discord"
            startContent={<DiscordIcon className={ic} />}
            style={{ color: "#5865F2" }}
          >
            Join Discord
          </DropdownItem>
          <DropdownItem
            key="whatsapp"
            startContent={<WhatsappIcon className={ic} />}
            style={{ color: "#25d366" }}
          >
            Join WhatsApp
          </DropdownItem>
        </DropdownSection>

        {/* Actions */}
        <DropdownSection>
          <DropdownItem
            key="download"
            startContent={<CloudDownloadIcon className={ic} />}
            endContent={<ArrowRight01Icon className="h-4 w-4 text-zinc-500" />}
            className="text-zinc-400 hover:text-white"
          >
            Download for Desktop
          </DropdownItem>
          <DropdownItem
            key="resources"
            startContent={<BookOpen02Icon className={ic} />}
            endContent={<ArrowRight01Icon className="h-4 w-4 text-zinc-500" />}
            className="text-zinc-400 hover:text-white"
          >
            Resources
          </DropdownItem>
          <DropdownItem
            key="support"
            startContent={<CustomerService01Icon className={ic} />}
            endContent={<ArrowRight01Icon className="h-4 w-4 text-zinc-500" />}
            className="text-zinc-400 hover:text-white"
          >
            Support
          </DropdownItem>
          <DropdownItem
            key="settings"
            startContent={<Settings01Icon className={ic} />}
            className="text-zinc-400 hover:text-white"
          >
            Settings
          </DropdownItem>
          <DropdownItem
            key="logout"
            startContent={<Logout02Icon className={ic} />}
            color="danger"
            className="text-danger"
          >
            Sign Out
          </DropdownItem>
        </DropdownSection>
      </DropdownMenu>
    </Dropdown>
  );
}

// ─── Demo model picker ────────────────────────────────────────────────────────
const DEMO_MODELS = [
  {
    id: "claude-haiku-4-5-20251001",
    name: "Claude Haiku 4.5",
    provider: "Anthropic",
    description: "Fast and compact. Best for simple tasks.",
    tier: "free",
    is_default: false,
    logo: "/images/logos/logo.webp",
  },
  {
    id: "claude-sonnet-4-5-20250929",
    name: "Claude Sonnet 4.5",
    provider: "Anthropic",
    description: "Balanced performance and intelligence.",
    tier: "free",
    is_default: true,
    logo: "/images/logos/logo.webp",
  },
  {
    id: "claude-opus-4-6",
    name: "Claude Opus 4.6",
    provider: "Anthropic",
    description: "Most capable. Best for complex reasoning.",
    tier: "pro",
    is_default: false,
    logo: "/images/logos/logo.webp",
  },
  {
    id: "grok-4-1",
    name: "Grok 4.1",
    provider: "xAI",
    description: "xAI's latest model with real-time web access.",
    tier: "pro",
    is_default: false,
    logo: "/images/icons/grok.webp",
  },
  {
    id: "gemini-3-flash",
    name: "Gemini 3 Flash",
    provider: "Google",
    description: "Fast and efficient for everyday tasks.",
    tier: "free",
    is_default: false,
    logo: "/images/icons/gemini.webp",
  },
  {
    id: "gemini-3-pro",
    name: "Gemini 3 Pro",
    provider: "Google",
    description: "Google's most advanced reasoning model.",
    tier: "pro",
    is_default: false,
    logo: "/images/icons/gemini.webp",
  },
];

const MODEL_PROVIDERS = ["Anthropic", "Google", "xAI"];

function DemoModelPicker() {
  const [selected, setSelected] = useState("claude-sonnet-4-5-20250929");
  const current = DEMO_MODELS.find((m) => m.id === selected);

  return (
    <Select
      selectedKeys={new Set([selected])}
      onSelectionChange={(keys) => {
        const k = Array.from(keys)[0];
        if (k && typeof k === "string") setSelected(k);
      }}
      variant="flat"
      aria-label="Select AI Model"
      className="w-fit! max-w-none!"
      popoverProps={{
        classNames: { content: "min-w-[340px] max-w-none bg-zinc-800" },
      }}
      classNames={{
        trigger:
          "cursor-pointer bg-transparent transition hover:bg-zinc-800! !min-w-fit !w-auto !max-w-none whitespace-nowrap px-2 pr-9 h-8",
        value: "text-zinc-400! text-xs font-medium whitespace-nowrap !w-auto",
        base: "!max-w-none !w-auto",
        innerWrapper: "!w-auto !max-w-none",
        mainWrapper: "!w-auto !max-w-none",
        selectorIcon: "text-zinc-500 h-4 w-4",
      }}
      scrollShadowProps={{ isEnabled: false }}
      startContent={
        <BubbleChatSparkIcon className="text-zinc-500" width={18} height={18} />
      }
      renderValue={() => <span>{current?.name ?? "Model"}</span>}
    >
      {MODEL_PROVIDERS.map((provider) => (
        <SelectSection
          key={provider}
          classNames={{
            heading:
              "flex w-full sticky top-0 z-20 py-2 px-2 bg-zinc-800 text-zinc-200 text-xs font-medium",
          }}
          title={provider}
        >
          {DEMO_MODELS.filter((m) => m.provider === provider).map((m) => (
            <SelectItem
              key={m.id}
              textValue={m.name}
              classNames={{
                base: "py-2.5 px-2 data-[hover=true]:bg-zinc-700/50 gap-3 items-start rounded-xl",
                title: "text-zinc-200",
              }}
              startContent={
                <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-zinc-700/50">
                  <Image
                    src={m.logo}
                    alt={m.provider}
                    width={20}
                    height={20}
                    className="h-5 w-5 rounded object-contain"
                  />
                </div>
              }
            >
              <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-zinc-100">
                    {m.name}
                  </span>
                  {m.is_default && (
                    <span className="rounded-full bg-green-500/20 px-1.5 py-0.5 text-[10px] text-green-400">
                      Default
                    </span>
                  )}
                  {m.tier === "pro" && (
                    <span className="rounded-full bg-yellow-500/20 px-1.5 py-0.5 text-[10px] text-yellow-400">
                      Pro
                    </span>
                  )}
                </div>
                <p className="text-xs text-zinc-400">{m.description}</p>
              </div>
            </SelectItem>
          ))}
        </SelectSection>
      ))}
    </Select>
  );
}

// ─── Chat tab with hover buttons ──────────────────────────────────────────────
function DemoChatTab({ label, active }: { label: string; active?: boolean }) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      className={`group relative flex cursor-pointer items-center rounded-lg px-2.5 py-1.5 text-sm transition-colors ${
        active
          ? "bg-zinc-800 text-zinc-100"
          : "text-zinc-500 hover:bg-zinc-800/60 hover:text-zinc-300"
      }`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <span className={`flex-1 truncate pr-1 ${hovered ? "opacity-60" : ""}`}>
        {label}
      </span>
      {hovered && (
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            className="flex h-5 w-5 items-center justify-center rounded text-zinc-400 hover:bg-zinc-700 hover:text-white"
            aria-label="Pin"
          >
            <PinIcon width={12} height={12} />
          </button>
          <button
            type="button"
            className="flex h-5 w-5 items-center justify-center rounded text-zinc-400 hover:bg-zinc-700 hover:text-white"
            aria-label="Rename"
          >
            <Edit02Icon width={12} height={12} />
          </button>
          <button
            type="button"
            className="flex h-5 w-5 items-center justify-center rounded text-zinc-400 hover:bg-red-500/20 hover:text-red-400"
            aria-label="Delete"
          >
            <Delete02Icon width={12} height={12} />
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────
function DemoSidebar({ open }: { open: boolean }) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <motion.div
      animate={{ width: open ? 208 : 0, opacity: open ? 1 : 0 }}
      transition={{ duration: 0.22, ease }}
      className="relative flex shrink-0 flex-col overflow-hidden"
      style={{ backgroundColor: "#1a1a1a" }}
    >
      <div className="flex h-full w-[208px] flex-col">
        {/* Logo header */}
        <div className="flex items-center px-2 py-2">
          <LogoWithContextMenu
            className="group flex items-center gap-2 px-1"
            width={80}
            height={24}
          />
        </div>

        {/* Nav buttons */}
        <div className="flex flex-col gap-0.5 px-1">
          {navButtons.map(({ Icon, label, active }) => (
            <div
              key={label}
              className={`flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm transition-colors ${
                active
                  ? "bg-zinc-800 text-zinc-200"
                  : "text-zinc-500 hover:bg-zinc-800/60 hover:text-zinc-300"
              }`}
            >
              <div className="flex w-[17px] min-w-[17px] items-center justify-center">
                <Icon width={17} height={17} />
              </div>
              <span className="truncate">{label}</span>
            </div>
          ))}
        </div>

        {/* New chat button */}
        <div className="px-2 pt-2">
          <button
            type="button"
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-2.5 py-1.5 text-sm font-medium text-white transition-colors hover:bg-primary/90"
          >
            <BubbleChatAddIcon width={16} height={16} />
            New Chat
          </button>
        </div>

        {/* Chat list — scrollable, with accordion groups */}
        <div className="mt-1 flex-1 overflow-y-auto px-1">
          <Accordion
            type="multiple"
            defaultValue={["Today", "Yesterday", "Last 30 days"]}
            className="space-y-0"
          >
            {Object.entries(chatGroups).map(([group, tabs]) => (
              <AccordionItem key={group} value={group} className="border-none">
                <AccordionTrigger className="w-full px-2 pb-1 pt-0 text-[10px] font-medium uppercase tracking-wider text-zinc-600 hover:text-zinc-600 hover:no-underline [&>svg]:h-3 [&>svg]:w-3 [&>svg]:text-zinc-600">
                  {group}
                </AccordionTrigger>
                <AccordionContent className="p-0">
                  <div className="flex flex-col gap-0.5 pb-1">
                    {tabs.map((tab) => (
                      <DemoChatTab
                        key={tab.id}
                        label={tab.label}
                        active={tab.active}
                      />
                    ))}
                  </div>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>

        {/* Footer */}
        <div className="px-2 pb-2">
          <DemoSettingsDropdown onOpenChange={setSettingsOpen}>
            <button
              type="button"
              className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-2 transition-colors hover:bg-zinc-800"
            >
              <div className="flex items-center gap-2.5">
                <Avatar className="size-7 shrink-0 rounded-full bg-black">
                  <AvatarImage
                    src="https://github.com/aryanranderiya.png"
                    alt="Aryan"
                  />
                  <AvatarFallback className="bg-zinc-700 text-xs text-zinc-300">
                    AR
                  </AvatarFallback>
                </Avatar>
                <div className="flex flex-col items-start -space-y-0.5">
                  <span className="text-xs font-medium text-zinc-200">
                    Aryan Randeriya
                  </span>
                  <span className="text-[10px] text-zinc-500">GAIA Pro</span>
                </div>
              </div>
              {settingsOpen ? (
                <ChevronsDownUp
                  className="shrink-0 text-zinc-500"
                  width={16}
                  height={16}
                />
              ) : (
                <ChevronsUpDown
                  className="shrink-0 text-zinc-500"
                  width={16}
                  height={16}
                />
              )}
            </button>
          </DemoSettingsDropdown>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Header button helper ─────────────────────────────────────────────────────
function HeaderBtn({
  Icon,
  label,
}: {
  Icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      className="group flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:text-primary"
    >
      <Icon className="h-5 w-5" />
    </button>
  );
}

// ─── Chat header ──────────────────────────────────────────────────────────────
function DemoChatHeader({
  sidebarOpen,
  onToggleSidebar,
}: {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
}) {
  return (
    <div className="flex h-11 shrink-0 items-center justify-between px-3">
      <div className="flex items-center gap-1">
        {/* Sidebar toggle */}
        <button
          type="button"
          onClick={onToggleSidebar}
          className="group flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:text-primary"
          aria-label="Toggle sidebar"
        >
          {sidebarOpen ? (
            <SidebarLeft01Icon className="h-5 w-5" />
          ) : (
            <SidebarRight01Icon className="h-5 w-5" />
          )}
        </button>
        {/* Model picker */}
        <DemoModelPicker />
      </div>
      <div className="flex items-center gap-0">
        <HeaderBtn Icon={SearchIcon} label="Search" />
        <HeaderBtn Icon={PinIcon} label="Pins" />
        <HeaderBtn Icon={BubbleChatAddIcon} label="New Chat" />
        <HeaderBtn Icon={NotificationIcon} label="Notifications" />
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
type Phase =
  | "idle"
  | "user_sent"
  | "thinking"
  | "fetching"
  | "emailing"
  | "tool_calls"
  | "responding"
  | "email_card"
  | "done";

export default function ChatDemoSection() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [phase, setPhase] = useState<Phase>("idle");
  const [loadingText, setLoadingText] = useState("GAIA is thinking...");
  const [loadingKey, setLoadingKey] = useState(0);
  const [loadingCat, setLoadingCat] = useState<string | undefined>();
  const [toolsExpanded, setToolsExpanded] = useState(false);
  const [typedResponse, setTypedResponse] = useState("");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const messagesRef = useRef<HTMLDivElement>(null);

  const clearAll = () => {
    for (const t of timers.current) clearTimeout(t);
    timers.current = [];
  };

  const add = (fn: () => void, delay: number) => {
    timers.current.push(setTimeout(fn, delay));
  };

  const scrollToBottom = () => {
    requestAnimationFrame(() => {
      if (messagesRef.current) {
        messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
      }
    });
  };

  const runAnimation = () => {
    clearAll();
    setPhase("idle");
    setLoadingText("GAIA is thinking...");
    setLoadingKey(0);
    setLoadingCat(undefined);
    setToolsExpanded(false);
    setTypedResponse("");

    add(() => {
      setPhase("user_sent");
      scrollToBottom();
    }, T.userMsg);

    add(() => {
      setPhase("thinking");
      setLoadingText("GAIA is thinking...");
      setLoadingKey((k) => k + 1);
      setLoadingCat(undefined);
      scrollToBottom();
    }, T.thinking);

    add(() => {
      setPhase("fetching");
      setLoadingText("Fetching Hacker News");
      setLoadingKey((k) => k + 1);
      setLoadingCat("web_search");
    }, T.fetching);

    add(() => {
      setPhase("emailing");
      setLoadingText("Composing email draft");
      setLoadingKey((k) => k + 1);
      setLoadingCat("gmail");
    }, T.emailing);

    add(() => {
      setPhase("tool_calls");
    }, T.toolCalls);

    add(() => {
      setPhase("responding");
      let i = 0;
      const tick = setInterval(() => {
        i += 3;
        setTypedResponse(BOT_RESPONSE.slice(0, i));
        if (i >= BOT_RESPONSE.length) {
          clearInterval(tick);
          setTypedResponse(BOT_RESPONSE);
        }
      }, 18);
    }, T.botResponse);

    add(() => {
      setPhase("email_card");
      scrollToBottom();
    }, T.emailCard);

    add(() => setPhase("done"), T.done);

    add(() => runAnimation(), T.loop);
  };

  useEffect(() => {
    runAnimation();
    return () => clearAll();
  }, []);

  const showUser = phase !== "idle";
  const showLoading = ["thinking", "fetching", "emailing"].includes(phase);
  const showTools = ["tool_calls", "responding", "email_card", "done"].includes(
    phase,
  );
  const showResponse = ["responding", "email_card", "done"].includes(phase);
  const showEmail = ["email_card", "done"].includes(phase);
  // GAIA logo only visible alongside bot response — aligned to bottom of response
  const showBotLogo = showTools || showResponse;

  return (
    <div className="relative mx-auto flex w-full max-w-6xl flex-col items-center px-4">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.4 }}
        className="mb-8 text-center"
      >
        <p className="mb-2 text-sm font-medium uppercase tracking-widest text-zinc-500">
          See it in action
        </p>
        <h2 className="text-3xl font-semibold tracking-tight text-white">
          Your assistant, actually working
        </h2>
      </motion.div>

      {/* Demo window */}
      <motion.div
        initial={{ opacity: 0, y: 24, scale: 0.97 }}
        whileInView={{ opacity: 1, y: 0, scale: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, ease }}
        className="w-full overflow-hidden rounded-2xl"
        style={
          {
            "--color-primary-bg": "#111111",
            height: 680,
            boxShadow: "0 32px 80px rgba(0,0,0,0.7)",
          } as React.CSSProperties
        }
      >
        {/* Traffic-light bar */}
        <div
          className="flex h-9 shrink-0 items-center gap-1.5 px-4"
          style={{ backgroundColor: "#1a1a1a" }}
        >
          <div className="h-3 w-3 cursor-pointer rounded-full bg-zinc-700 transition-colors hover:bg-red-500" />
          <div className="h-3 w-3 cursor-pointer rounded-full bg-zinc-700 transition-colors hover:bg-yellow-400" />
          <div className="h-3 w-3 cursor-pointer rounded-full bg-zinc-700 transition-colors hover:bg-green-500" />
          <div className="ml-4 flex-1 text-center text-[11px] text-zinc-500">
            GAIA — Personal AI Assistant
          </div>
        </div>

        {/* Body */}
        <div className="flex" style={{ height: "calc(100% - 36px)" }}>
          {/* Sidebar */}
          <DemoSidebar open={sidebarOpen} />

          {/* Chat column */}
          <div
            className="flex min-w-0 flex-1 flex-col"
            style={{ backgroundColor: "#111111" }}
          >
            {/* Header */}
            <DemoChatHeader
              sidebarOpen={sidebarOpen}
              onToggleSidebar={() => setSidebarOpen((o) => !o)}
            />

            {/* Messages — scrollable */}
            <div ref={messagesRef} className="flex-1 overflow-y-auto px-5 py-2">
              <AnimatePresence>
                {/* User message */}
                {showUser && (
                  <motion.div
                    key="user-msg"
                    variants={slideUp}
                    initial="initial"
                    animate="animate"
                    exit="exit"
                    transition={tx}
                    className="mb-4 flex items-end justify-end gap-2"
                  >
                    <div className="imessage-bubble imessage-from-me max-w-[72%] text-sm">
                      Fetch top stories from Hacker News and send me an email
                      digest
                    </div>
                    <Avatar className="size-7 shrink-0 rounded-full border border-white/10">
                      <AvatarImage
                        src="https://github.com/aryanranderiya.png"
                        alt="Aryan"
                      />
                      <AvatarFallback className="bg-primary/20 text-xs font-medium text-primary">
                        AR
                      </AvatarFallback>
                    </Avatar>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Bot row — loading phase has no logo, logo only with response */}
              <div className="flex items-end gap-2.5">
                {/* GAIA logo — only shown alongside bot response, pinned to bottom */}
                <div className="relative w-8 shrink-0">
                  <AnimatePresence>
                    {showBotLogo && (
                      <motion.div
                        key="bot-logo"
                        initial={{ opacity: 0, scale: 0.8 }}
                        animate={{ opacity: 1, scale: 1 }}
                        transition={tx}
                      >
                        <Image
                          src="/images/logos/logo.webp"
                          width={28}
                          height={28}
                          alt="GAIA"
                          className="transition-all duration-700"
                        />
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>

                <div className="flex min-w-0 flex-1 flex-col gap-2">
                  {/* Loading — no logo during this phase */}
                  <AnimatePresence mode="wait">
                    {showLoading && (
                      <motion.div
                        key="loading"
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -6 }}
                        transition={tx}
                        className="flex items-center gap-3"
                      >
                        {loadingCat ? (
                          getToolCategoryIcon(loadingCat, {
                            size: 18,
                            width: 18,
                            height: 18,
                            iconOnly: true,
                            pulsating: true,
                          })
                        ) : (
                          <MiniWaveSpinner />
                        )}
                        <AnimatePresence mode="wait">
                          <motion.span
                            key={loadingKey}
                            variants={slideUp}
                            initial="initial"
                            animate="animate"
                            exit="exit"
                            transition={tx}
                            className="animate-shine bg-size-[200%_100%] w-fit bg-clip-text text-sm font-medium text-transparent"
                            style={{
                              backgroundImage:
                                "linear-gradient(90deg, rgb(255 255 255 / 0.3) 20%, rgb(255 255 255) 50%, rgb(255 255 255 / 0.3) 80%)",
                            }}
                          >
                            {loadingText}
                          </motion.span>
                        </AnimatePresence>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Tool calls */}
                  <AnimatePresence>
                    {showTools && (
                      <DemoToolCalls
                        expanded={toolsExpanded}
                        onToggle={() => setToolsExpanded((e) => !e)}
                      />
                    )}
                  </AnimatePresence>

                  {/* Bot text response */}
                  <AnimatePresence>
                    {showResponse && (
                      <motion.div
                        key="bot-response"
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={tx}
                        className="imessage-bubble imessage-from-them max-w-[90%] text-sm text-white"
                      >
                        {typedResponse}
                        {phase === "responding" && (
                          <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse bg-white/60 align-middle" />
                        )}
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Email compose card */}
                  <AnimatePresence>
                    {showEmail && (
                      <motion.div
                        key="email-card"
                        initial={{ opacity: 0, y: 10, scale: 0.97 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        transition={{
                          duration: 0.3,
                          ease: [0.34, 1.2, 0.64, 1],
                        }}
                        className="mb-4"
                      >
                        <EmailComposeCard
                          emailData={DEMO_EMAIL}
                          onSent={() => {}}
                        />
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </div>
            </div>

            {/* Composer — 65% width centered like real chat */}
            <div className="relative shrink-0 px-4 pb-4 [&_.searchbar]:!w-[65%] [&_.searchbar_container]:!w-full">
              <DummyComposer />
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
