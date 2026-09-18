import { Avatar } from "@heroui/avatar";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Divider } from "@heroui/divider";
import { Link } from "@heroui/link";
import { Spinner } from "@heroui/spinner";
import {
  Alert01Icon,
  ArrowUpRight01Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  FavouriteIcon,
  Link01Icon,
  Loading03Icon,
  Tick02Icon,
} from "@icons";
import type { ReactNode } from "react";
import CalendarEventSection from "@/features/chat/components/bubbles/bot/CalendarEventSection";
import EmailThreadCard from "@/features/chat/components/bubbles/bot/EmailThreadCard";
import RateLimitCard from "@/features/chat/components/bubbles/bot/RateLimitCard";
import TodoSection from "@/features/chat/components/bubbles/bot/TodoSection";
import TwitterSearchSection from "@/features/chat/components/bubbles/bot/TwitterSearchSection";
import CalendarEventSectionBefore from "./before/CalendarEventSectionBefore";
import EmailThreadCardBefore from "./before/EmailThreadCardBefore";
import RateLimitCardBefore from "./before/RateLimitCardBefore";
import TodoSectionBefore from "./before/TodoSectionBefore";
import TwitterSearchSectionBefore from "./before/TwitterSearchSectionBefore";
import {
  MOCK_CALENDAR_OPTIONS,
  MOCK_EMAIL_THREAD,
  MOCK_RATE_LIMIT,
  MOCK_TODO_STATS,
  MOCK_TWEET,
} from "./mocks";

export const SHOWCASE_RULES = [
  "shadcn/no-restyle",
  "shadcn/no-raw-colors",
  "shadcn/no-arbitrary-values",
  "shadcn/no-inline-styles",
  "shadcn/no-unknown-classes",
  "shadcn/require-static-classes",
] as const;

export type ShowcaseRule = (typeof SHOWCASE_RULES)[number];

export interface RuleGuide {
  rule: ShowcaseRule;
  what: string;
  why: string;
  params: string;
}

export const RULE_GUIDE: RuleGuide[] = [
  {
    rule: "shadcn/no-restyle",
    what: "It catches className overrides on UI components that fight the component's own built-in variants.",
    why: "GAIA cards must all obey the DESIGN.md card contract (outer rounded-3xl bg-zinc-800 p-4, inner rounded-2xl bg-zinc-900 p-3, no borders, status tints at /10) and HeroUI components must be styled through variant and color props, so one fix in the component fixes every surface.",
    params:
      "Error. Allows layout classes like mt-4 and w-full on any component; everything else on a component must be a variant. Named carve-outs exist for RaisedButton, InputOTP parts, Separator, GrainOverlay, Skeleton, the message scroller, CopyButton, Calendar, ProgressiveImage, SidebarInset, SidebarHeader, and ModalBody.",
  },
  {
    rule: "shadcn/no-raw-colors",
    what: "It catches hard-coded colors that are not part of the theme, such as bg-gray-800, text-green-500, or bg-[#1d9bf0].",
    why: "GAIA renders on a zinc foundation with a fixed set of status colors from DESIGN.md (emerald, amber, red, blue and friends at /10 backgrounds with full-color text), so a stray gray or brand-blue hex breaks the dark-room look everywhere it appears.",
    params:
      "Error. Allows the zinc scale, the status accents (emerald / amber / red / blue / yellow / orange 400-500, violet / lime / purple-400), every semantic theme token (foreground, danger, warning, success, background, popover, muted, accent, ring, destructive, input, card, secondary, default), plus text-pink-400, the tiny text sizes, and the custom gradient.",
  },
  {
    rule: "shadcn/no-arbitrary-values",
    what: "It catches one-off bracket values like text-[11px] or px-[10px] that dodge the Tailwind scale.",
    why: "The DESIGN.md card contract is built from scale steps (rounded-3xl shells, rounded-xl pills, text-xs detail copy), so arbitrary values let cards drift a pixel at a time until no two cards agree.",
    params:
      "Error. Allows layout plus a listed set of one-offs: the transition and duration tokens, the letter-art CSS variables, the iPhone hardware radii (56px / 46px), blur, drop-shadow, and hero spacing values.",
  },
  {
    rule: "shadcn/no-inline-styles",
    what: "It catches style={{ ... }} props that hide design decisions where the class system cannot see them.",
    why: "HeroUI components take color and shape through props and GAIA surfaces through classes, so an inline backgroundColor is invisible to theming and to every other lint rule.",
    params:
      "Warning. No inline styles by default; narrow per-folder allows cover measured geometry (calendar widths and positions, virtualizer transforms, map chrome) and genuinely dynamic paint (Google calendar pill colors, heatmap cells).",
  },
  {
    rule: "shadcn/no-unknown-classes",
    what: "It catches typos and non-existent classes like bg-zinc-750 that compile fine but silently do nothing.",
    why: "A dead class on a card looks like a styling decision to the next reader, so the card contract rots one invisible no-op at a time.",
    params:
      "Warning. Allows the intentional custom classes: ph-no-capture, tool-icon-btn, slash-command-dropdown, compact-chat, mermaid, colored, and markdown-table.",
  },
  {
    rule: "shadcn/require-static-classes",
    what: "It catches dynamically built class strings, such as template literals that interpolate variables into class names.",
    why: "The linter and Tailwind can only verify classes they can read literally, so a constructed string hides violations of the card contract and the color rules above.",
    params:
      "Warning. No parameters: always pick between complete static strings (a ternary of two full class lists is fine) instead of interpolating fragments into one string.",
  },
];

export interface ShowcaseExemption {
  label: string;
  reason: string;
}

export const SHOWCASE_EXEMPTIONS: ShowcaseExemption[] = [
  {
    label: "Brand SVG fills",
    reason:
      "Gmail and Google Calendar icons use their official multi-color fills.",
  },
  {
    label: "Parchment art",
    reason: "The founder-letter artwork uses its own paper palette.",
  },
  {
    label: "Google-calendar pills",
    reason: "Event bars render the background_color hexes Google sends us.",
  },
  {
    label: "Gender pink",
    reason: "text-pink-400 marks the feminine voice filter.",
  },
  {
    label: "iPhone hardware radii",
    reason: "rounded-[56px] / [46px] match the physical iPhone corners.",
  },
  {
    label: "Heatmap cells",
    reason: "Usage-heatmap cells need computed intensity color steps.",
  },
  {
    label: "OS-banner notification",
    reason:
      "SendNotificationSection deliberately mimics an OS notification banner.",
  },
  {
    label: "Dev gallery",
    reason:
      "dev/** routes stay exempt so this page can render violations on purpose.",
  },
  {
    label: "OG routes",
    reason: "app/api/og images need inline geometry for server-side rendering.",
  },
  {
    label: "Virtualizer geometry",
    reason: "The todo virtualizer sets measured height and transform inline.",
  },
  {
    label: "Map chrome",
    reason: "The map component uses geographic fill and line hexes.",
  },
];

export interface ShowcaseSection {
  title: string;
  rule: ShowcaseRule;
  change: string;
  before: ReactNode;
  beforeCaption: string;
  afterCaption: string;
  after: ReactNode;
}

export const MOCK_TWEETS = { tweets: [MOCK_TWEET], result_count: 1 };

// Resolved from mock data so the S1 demo below branches on a runtime value.
const isLive = MOCK_TWEETS.result_count === 1;

export const SHOWCASE_SECTIONS: ShowcaseSection[] = [
  {
    title: "F1 Outer radius 2xl to 3xl",
    rule: "shadcn/no-arbitrary-values",
    change: "Outer radius 2xl goes to 3xl to match the card contract.",
    before: (
      <div className="rounded-2xl bg-zinc-800 p-4">
        <span className="text-sm font-medium text-zinc-200">Design review</span>
      </div>
    ),
    beforeCaption: "rounded-2xl bg-zinc-800 p-4 (old rule)",
    afterCaption: "rounded-3xl bg-zinc-800 p-4 (new rule)",
    after: (
      <div className="rounded-3xl bg-zinc-800 p-4">
        <span className="text-sm font-medium text-zinc-200">Design review</span>
      </div>
    ),
  },
  {
    title: "F2 Small radius lg to xl",
    rule: "shadcn/no-arbitrary-values",
    change: "Pill radius lg goes to xl for status pills.",
    before: (
      <span className="rounded-lg bg-zinc-700 px-2 py-1 text-xs font-medium text-zinc-200">
        In progress
      </span>
    ),
    beforeCaption: "rounded-lg bg-zinc-700 px-2 py-1",
    afterCaption:
      "rounded-xl bg-zinc-700 px-2 py-1 text-xs font-medium text-zinc-200 + h-4 w-4 text-emerald-400",
    after: (
      <div className="flex items-center gap-2">
        <span className="rounded-xl bg-zinc-700 px-2 py-1 text-xs font-medium text-zinc-200">
          In progress
        </span>
        <Tick02Icon className="h-4 w-4 text-emerald-400" />
      </div>
    ),
  },
  {
    title: "F3 Border removal",
    rule: "shadcn/no-unknown-classes",
    change: "Border wrapper goes to Avatar plus truncate, no border.",
    before: (
      // biome-ignore lint: intentional violation gallery (F3 before)
      <div className="border border-zinc-700 bg-zinc-900 p-3">
        <p className="text-sm font-medium text-zinc-200">GAIA</p>
        <p className="text-xs text-zinc-500">@heygaia</p>
      </div>
    ),
    beforeCaption: "border border-zinc-700 bg-zinc-900",
    afterCaption:
      "Avatar name=GAIA size=sm + truncate text-sm font-medium text-zinc-200 + text-xs text-zinc-500 (no border)",
    after: (
      <div className="flex items-center gap-3">
        <Avatar name="GAIA" size="sm" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-zinc-200">GAIA</p>
          <p className="text-xs text-zinc-500">@heygaia</p>
        </div>
      </div>
    ),
  },
  {
    title: "F4 Separators to Divider",
    rule: "shadcn/no-unknown-classes",
    change: "Raw h-px div goes to the Divider component.",
    before: (
      <div className="flex flex-col gap-2">
        <p className="text-sm text-zinc-200">Design review</p>
        <div className="h-px bg-zinc-700" />
        <p className="text-xs text-zinc-500">Today at 10:00</p>
      </div>
    ),
    beforeCaption: "h-px bg-zinc-700",
    afterCaption: "Divider className=bg-zinc-700/50",
    after: (
      <div className="flex flex-col gap-2">
        <p className="text-sm text-zinc-200">Design review</p>
        <Divider className="bg-zinc-700/50" />
        <p className="text-xs text-zinc-500">Today at 10:00</p>
      </div>
    ),
  },
  {
    title: "F5 Arbitrary values to scale",
    rule: "shadcn/no-arbitrary-values",
    change: "Arbitrary hex and pixel steps go to theme tokens.",
    before: (
      <span className="rounded-full bg-[#1d9bf0] px-[10px] py-0.5 text-[11px] font-medium text-white">
        New
      </span>
    ),
    beforeCaption: "bg-[#1d9bf0] text-[11px] px-[10px]",
    afterCaption:
      "rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary",
    after: (
      <div className="flex items-center gap-2">
        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
          New
        </span>
        <span className="text-xs text-zinc-400">2 replies in the thread</span>
      </div>
    ),
  },
  {
    title: "F6 Status tint at 10 percent",
    rule: "shadcn/no-restyle",
    change: "Solid 20 percent tint goes to flat Chip at 10 percent.",
    before: (
      // biome-ignore lint: intentional violation gallery (F6 before)
      <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-xs font-medium text-emerald-300">
        Active
      </span>
    ),
    beforeCaption: "bg-emerald-500/20 text-emerald-300",
    afterCaption:
      "Chip flat: base bg-emerald-400/10, content text-xs font-medium text-emerald-400",
    after: (
      <Chip
        size="sm"
        variant="flat"
        classNames={{
          base: "bg-emerald-400/10",
          content: "text-xs font-medium text-emerald-400",
        }}
      >
        Active
      </Chip>
    ),
  },
  {
    title: "F7 Gray to zinc",
    rule: "shadcn/no-raw-colors",
    change: "Gray palette goes to the zinc foundation.",
    before: (
      <span className="rounded-xl bg-gray-800 px-2 py-1 text-xs text-gray-400">
        Draft
      </span>
    ),
    beforeCaption: "bg-gray-800 text-gray-400",
    afterCaption: "rounded-xl bg-zinc-700 px-2 py-1 text-xs text-zinc-400",
    after: (
      <div className="flex items-center gap-2">
        <span className="rounded-xl bg-zinc-700 px-2 py-1 text-xs text-zinc-400">
          Draft
        </span>
        <span className="text-xs text-zinc-500">Saved just now</span>
      </div>
    ),
  },
  {
    title: "F8 Inline style to classes",
    rule: "shadcn/no-inline-styles",
    change: "Inline backgroundColor goes to a static class.",
    before: (
      <div className="flex items-center gap-2">
        <span
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: "#22c55e" }}
        />
        <span className="text-xs text-zinc-400">All systems online</span>
      </div>
    ),
    beforeCaption: "style={{ backgroundColor: statusColor }}",
    afterCaption: "h-2 w-2 rounded-full bg-emerald-400",
    after: (
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 rounded-full bg-emerald-400" />
        <span className="text-xs text-zinc-400">All systems online</span>
      </div>
    ),
  },
  {
    title: "F9 Raw elements to HeroUI",
    rule: "shadcn/no-restyle",
    change: "Native button and anchor go to HeroUI Button plus Link.",
    before: (
      <div className="flex items-center gap-3">
        <button
          className="rounded-lg bg-primary px-3 py-1.5 text-sm text-white"
          type="button"
        >
          Follow
        </button>
        <a className="text-sm text-primary" href="https://x.com/heygaia">
          View post
        </a>
      </div>
    ),
    beforeCaption:
      "<button>Follow</button> <a href=https://x.com/heygaia>View</a>",
    afterCaption:
      "Button color=primary size=sm + Link color=primary size=sm href=/ + h-3.5 w-3.5 text-zinc-500",
    after: (
      <div className="flex items-center gap-3">
        <Button
          color="primary"
          size="sm"
          startContent={<FavouriteIcon className="h-4 w-4" />}
        >
          Follow
        </Button>
        <div className="flex items-center gap-1">
          <Link01Icon className="h-3.5 w-3.5 text-zinc-500" />
          <Link color="primary" href="/" size="sm">
            View post
          </Link>
        </div>
      </div>
    ),
  },
  {
    title: "F10 Unicode glyphs to icons",
    rule: "shadcn/no-restyle",
    change: "Text glyphs go to icon components.",
    before: (
      <div className="flex items-center gap-1 text-sm text-zinc-200">
        <span>Done</span>
        {/* biome-ignore lint: intentional violation gallery */}
        <span>✓</span>
        {/* biome-ignore lint: intentional violation gallery */}
        <span>•</span>
        <span>View</span>
        {/* biome-ignore lint: intentional violation gallery */}
        <span>→</span>
      </div>
    ),
    beforeCaption: "Done ✓ • View →",
    afterCaption:
      "CheckmarkCircle02Icon h-4 w-4 text-emerald-400 + text-sm text-zinc-200 + ArrowUpRight01Icon h-4 w-4 text-zinc-500",
    after: (
      <div className="flex items-center gap-2">
        <CheckmarkCircle02Icon className="h-4 w-4 text-emerald-400" />
        <span className="text-sm text-zinc-200">Deployed</span>
        <ArrowUpRight01Icon className="h-4 w-4 text-zinc-500" />
      </div>
    ),
  },
  {
    title: "F11 Icon spinner to Spinner",
    rule: "shadcn/no-restyle",
    change: "Animated icon goes to the HeroUI Spinner.",
    before: (
      <div className="flex items-center gap-2">
        <Loading03Icon className="h-4 w-4 animate-spin text-zinc-400" />
        <span className="text-xs text-zinc-400">Summarizing thread</span>
      </div>
    ),
    beforeCaption: '<Loading03Icon className="animate-spin" />',
    afterCaption: "Spinner size=sm",
    after: (
      <div className="flex items-center gap-2">
        <Spinner size="sm" />
        <span className="text-xs text-zinc-400">Summarizing thread</span>
      </div>
    ),
  },
  {
    title: "F12 Tabular numbers",
    rule: "shadcn/require-static-classes",
    change: "Jittery time text goes to tabular-nums plus icon.",
    before: (
      <div className="flex items-center gap-2">
        <span className="text-xs text-zinc-400">10:00-11:30</span>
      </div>
    ),
    beforeCaption: "<span>10:00</span> jitters in a list",
    afterCaption: "text-xs text-zinc-400 tabular-nums + h-4 w-4 text-zinc-500",
    after: (
      <div className="flex items-center gap-2">
        <Clock01Icon className="h-4 w-4 text-zinc-500" />
        <span className="text-xs text-zinc-400 tabular-nums">10:00-11:30</span>
      </div>
    ),
  },
  {
    title: "F13 Shadow removal",
    rule: "shadcn/no-raw-colors",
    change: "Heavy shadow goes to a flat surface plus icon.",
    before: (
      // biome-ignore lint: intentional violation gallery (F13 before)
      <div className="bg-zinc-800 p-3 shadow-xl shadow-black/50">
        <span className="text-xs text-zinc-400">Flat surface, no shadow</span>
      </div>
    ),
    beforeCaption: "shadow-xl shadow-black/50 bg-zinc-800",
    afterCaption: "h-4 w-4 text-amber-400 + text-xs text-zinc-400 (no shadow)",
    after: (
      <div className="flex items-center gap-2">
        <Alert01Icon className="h-4 w-4 text-amber-400" />
        <span className="text-xs text-zinc-400">Flat surface, no shadow</span>
      </div>
    ),
  },
  {
    title: "F14 Invalid classes",
    rule: "shadcn/no-unknown-classes",
    change: "Dead zinc-750 class goes to a valid zinc shade.",
    before: (
      <div className="bg-zinc-750 px-2 py-1">
        <span className="text-xs text-zinc-200">Pro</span>
      </div>
    ),
    beforeCaption: "bg-zinc-750 hover:bg-zinc-",
    afterCaption:
      "rounded-xl bg-zinc-700 px-2 py-1 text-xs font-medium text-zinc-200",
    after: (
      <div className="flex items-center gap-2">
        <span className="rounded-xl bg-zinc-700 px-2 py-1 text-xs font-medium text-zinc-200">
          Pro
        </span>
        <span className="text-xs text-zinc-500">Valid scale shades only</span>
      </div>
    ),
  },
  {
    title: "S1 Dynamic template to static strings",
    rule: "shadcn/require-static-classes",
    change: "Runtime template string goes to a static ternary.",
    before: (
      <span
        className={`rounded-full px-2 py-0.5 text-xs font-medium ${isLive ? "bg-emerald-400/10 text-emerald-400" : "bg-zinc-700 text-zinc-400"}`}
      >
        Live
      </span>
    ),
    beforeCaption:
      "className built with backticks plus a live-tint ternary (built at runtime)",
    afterCaption:
      "ternary of two full static strings: rounded-full bg-emerald-400/10 ... / rounded-full bg-zinc-700 ...",
    after: (
      <span
        className={
          isLive
            ? "rounded-full bg-emerald-400/10 px-2 py-0.5 text-xs font-medium text-emerald-400"
            : "rounded-full bg-zinc-700 px-2 py-0.5 text-xs font-medium text-zinc-400"
        }
      >
        Live
      </span>
    ),
  },
];

export interface FullCardExample {
  rule: ShowcaseRule;
  title: string;
  change: string;
  beforeCaption: string;
  afterCaption: string;
  before: ReactNode;
  after: ReactNode;
}

export const FULL_CARD_EXAMPLES: FullCardExample[] = [
  {
    rule: "shadcn/no-restyle",
    title: "TwitterSearchSection",
    change:
      "TwitterSearchSection: Radix avatar, border + bg-content1/50 card, text-[#1d9bf0] accents to HeroUI avatar, borderless zinc-900 card, text-primary. Also trips shadcn/no-raw-colors (the #1d9bf0 hex) and shadcn/no-unknown-classes (the content1 / foreground tokens).",
    beforeCaption:
      "rounded-xl border border-default-200 bg-content1/50 p-4 + text-[#1d9bf0] (Radix avatar)",
    afterCaption:
      "rounded-2xl bg-zinc-900 p-3 (no border) + text-primary (HeroUI Avatar)",
    before: <TwitterSearchSectionBefore twitter_search_data={MOCK_TWEETS} />,
    after: <TwitterSearchSection twitter_search_data={MOCK_TWEETS} />,
  },
  {
    rule: "shadcn/no-restyle",
    title: "EmailThreadCard",
    change:
      "EmailThreadCard: text-gray-500 empty state, shadow-md wrapper, rounded-lg body to zinc-500, flat wrapper, rounded-xl body. The before wrapper also builds its className with backticks, which shadcn/require-static-classes flags.",
    beforeCaption: "text-gray-500 + shadow-md + rounded-lg bg-white p-4",
    afterCaption:
      "text-zinc-500 + flat wrapper (no shadow) + rounded-xl bg-white p-4",
    before: <EmailThreadCardBefore emailThreadData={MOCK_EMAIL_THREAD} />,
    after: <EmailThreadCard emailThreadData={MOCK_EMAIL_THREAD} />,
  },
  {
    rule: "shadcn/no-raw-colors",
    title: "TodoSection (stats header)",
    change:
      "TodoSection stats: solid 500 stat colors with no tabular-nums to 400 tints with tabular-nums.",
    beforeCaption:
      "text-green-500 / text-yellow-500 / text-red-500 / text-blue-500 / text-purple-500 (no tabular-nums)",
    afterCaption:
      "text-emerald-400 / text-amber-400 / text-red-400 / text-blue-400 / text-purple-400 + tabular-nums",
    before: <TodoSectionBefore action="stats" stats={MOCK_TODO_STATS} />,
    after: <TodoSection action="stats" stats={MOCK_TODO_STATS} />,
  },
  {
    rule: "shadcn/no-arbitrary-values",
    title: "RateLimitCard",
    change:
      "RateLimitCard: rounded-3xl outer with /15 tints and text-[11px] detail to rounded-3xl with /10 tints and text-xs. Also trips shadcn/no-restyle (the rounded-3xl card contract) and shadcn/require-static-classes (template-literal tint classes).",
    beforeCaption:
      "rounded-3xl bg-zinc-800 + bg-warning/15 / bg-red-500/15 + text-[11px]",
    afterCaption:
      "rounded-3xl bg-zinc-800 + bg-warning/10 / bg-red-500/10 + text-xs",
    before: <RateLimitCardBefore data={MOCK_RATE_LIMIT} />,
    after: <RateLimitCard data={MOCK_RATE_LIMIT} />,
  },
  {
    rule: "shadcn/no-inline-styles",
    title: "CalendarEventSection",
    change:
      "CalendarEventSection: rounded-3xl outer, border-t separators, rounded-lg rows and bullet separator to rounded-3xl, Divider rows, rounded-xl, clean meta line. The before rows also paint Google pill colors via style={{ backgroundColor }} (see shadcn/no-inline-styles) and join meta with a bullet (see shadcn/no-unknown-classes companions).",
    beforeCaption:
      "rounded-3xl bg-zinc-800 p-4 + border-t border-zinc-700 + rounded-lg p-3 pl-5 + •",
    afterCaption:
      "rounded-3xl bg-zinc-800 p-4 + Divider bg-zinc-700/50 + rounded-xl p-3 pl-5 (no bullet)",
    before: (
      <CalendarEventSectionBefore calendar_options={MOCK_CALENDAR_OPTIONS} />
    ),
    after: <CalendarEventSection calendar_options={MOCK_CALENDAR_OPTIONS} />,
  },
];

export function getPairCount(rule: ShowcaseRule): number {
  const fullCount = FULL_CARD_EXAMPLES.filter(
    (example) => example.rule === rule,
  ).length;
  const snippetCount = SHOWCASE_SECTIONS.filter(
    (section) => section.rule === rule,
  ).length;
  return fullCount + snippetCount;
}

export function getRuleStatus(params: string): string {
  return params.startsWith("Error")
    ? "enforced as error"
    : "enforced as warning";
}

export function formatShowcaseBadge(n: number): string {
  return String(n).padStart(2, "0");
}
