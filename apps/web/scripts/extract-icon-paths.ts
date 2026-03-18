/**
 * Build script to extract SVG path data from gaia-icons React components
 *
 * Run with: npx tsx apps/web/scripts/extract-icon-paths.ts
 *
 * This generates a JSON file with pre-extracted SVG paths that can be used
 * in React Native (mobile) and Edge runtime (OG image generation).
 */

// Solid-rounded: tool category icons (filled style)
import {
  AlarmClockIcon,
  BodyPartMuscleIcon,
  Brain02Icon,
  CheckListIcon,
  ComputerTerminal01Icon,
  ConnectIcon,
  FileEmpty02Icon,
  FolderFileStorageIcon,
  Image02Icon,
  InformationCircleIcon,
  NotificationIcon,
  PackageOpenIcon,
  PuzzleIcon,
  SourceCodeCircleIcon,
  SquareArrowUpRight02Icon,
  Target02Icon,
  TaskDailyIcon,
  ToolsIcon,
  WorkflowCircle06Icon,
  ZapIcon,
} from "@theexperiencecompany/gaia-icons/solid-rounded";

// Stroke-rounded: UI icons (outline style — matches @hugeicons default)
import {
  Add01Icon,
  AiChipIcon,
  Alert01Icon,
  AlertCircleIcon,
  Analytics01Icon,
  ArrowDown01Icon,
  ArrowDown02Icon,
  ArrowDownIcon,
  ArrowLeft01Icon,
  ArrowRight01Icon,
  ArrowUp01Icon,
  ArrowUp02Icon,
  ArrowUpRight01Icon,
  BarChartIcon,
  BookOpen01Icon,
  BrainIcon,
  BubbleChatAddIcon,
  BubbleChatIcon,
  Calendar03Icon,
  Call02Icon,
  Camera01Icon,
  Cancel01Icon,
  ChartLineData01Icon,
  ChartLineData02Icon,
  ChartRingIcon,
  CheckmarkCircle01Icon,
  CheckmarkCircle02Icon,
  CheckmarkSquare03Icon,
  Clock01Icon,
  Clock04Icon,
  CloudAngledRainIcon,
  CloudAngledZapIcon,
  CloudFastWindIcon,
  CloudIcon,
  CloudLittleRainIcon,
  CloudSnowIcon,
  CodeIcon,
  Comment01Icon,
  Contact01Icon,
  Copy01Icon,
  CpuIcon,
  CreditCardIcon,
  CustomerSupportIcon,
  Delete01Icon,
  Delete02Icon,
  DiscordIcon,
  DocumentAttachmentIcon,
  Download02Icon,
  Download04Icon,
  DropletIcon,
  Edit02Icon,
  FastWindIcon,
  FavouriteIcon,
  File01Icon,
  Flag02Icon,
  FlashIcon,
  FlowCircleIcon,
  Flowchart01Icon,
  FlowIcon,
  Folder02Icon,
  FolderIcon,
  Globe02Icon,
  GlobeIcon,
  HelpCircleIcon,
  Image01Icon,
  KeyboardIcon,
  LayoutGridIcon,
  LinkBackwardIcon,
  LinkSquare01Icon,
  LinkSquare02Icon,
  Loading03Icon,
  Location01Icon,
  Logout01Icon,
  MagicWand01Icon,
  Mail01Icon,
  MailOpen01Icon,
  MailSend01Icon,
  Menu01Icon,
  Message01Icon,
  MessageMultiple01Icon,
  MoreVerticalIcon,
  News01Icon,
  Notification01Icon,
  Notification02Icon,
  PencilEdit01Icon,
  PencilEdit02Icon,
  PieChart01Icon,
  Pin02Icon,
  PlayIcon,
  PlusSignIcon,
  RepeatIcon,
  Search01Icon,
  SentIcon,
  Settings01Icon,
  Settings02Icon,
  Share01Icon,
  Share08Icon,
  ShieldUserIcon,
  Sun03Icon,
  SunriseIcon,
  SunsetIcon,
  Tag01Icon,
  TelegramIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  Tick01Icon,
  Tick02Icon,
  ToggleOffIcon,
  ToggleOnIcon,
  Tornado02Icon,
  TranslationIcon,
  TwitterIcon,
  UploadCircle01Icon,
  UserCircle02Icon,
  UserCircleIcon,
  UserGroupIcon,
  UserIcon,
  UserSearch01Icon,
  WhatsappIcon,
  WorkflowSquare10Icon,
  Wrench01Icon,
} from "@theexperiencecompany/gaia-icons/stroke-rounded";

import * as fs from "fs";
import * as path from "path";
// ESM-compatible directory resolution
import { dirname } from "path";
import * as React from "react";
import * as ReactDOMServer from "react-dom/server";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

type IconComponent = React.ComponentType<{
  size?: number;
  color?: string;
  strokeWidth?: number;
}>;

interface ExtractedSvgData {
  viewBox: string;
  paths: string[];
}

/**
 * Extract SVG path data from a gaia-icons component.
 * Handles both filled (solid) and stroked icons by extracting all path
 * and shape elements and normalising them to a fill-only representation
 * so they can be rendered with react-native-svg <Path fill={color} />.
 */
function extractSvgPaths(
  IconComponent: IconComponent,
  style: "solid" | "stroke",
): ExtractedSvgData {
  const html = ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComponent, {
      size: 24,
      color: style === "stroke" ? "currentColor" : "currentColor",
      strokeWidth: style === "stroke" ? 1.5 : undefined,
    }),
  );

  // Extract viewBox
  const viewBoxMatch = html.match(/viewBox="([^"]+)"/);
  const viewBox = viewBoxMatch?.[1] || "0 0 24 24";

  // Extract all path d attributes (works for both fill and stroke paths)
  const pathRegex = /<path[^>]*\sd="([^"]+)"[^>]*/g;
  const paths: string[] = [];
  for (const match of html.matchAll(pathRegex)) {
    if (match[1]) {
      paths.push(match[1]);
    }
  }

  return { viewBox, paths };
}

// Solid-rounded tool category icons
const solidIcons: Record<string, IconComponent> = {
  AlarmClockIcon,
  BodyPartMuscleIcon,
  Brain02Icon,
  CheckListIcon,
  ComputerTerminal01Icon,
  ConnectIcon,
  FileEmpty02Icon,
  FolderFileStorageIcon,
  Image02Icon,
  InformationCircleIcon,
  NotificationIcon,
  PackageOpenIcon,
  PuzzleIcon,
  SourceCodeCircleIcon,
  SquareArrowUpRight02Icon,
  Target02Icon,
  TaskDailyIcon,
  ToolsIcon,
  WorkflowCircle06Icon,
  ZapIcon,
};

// Stroke-rounded UI icons
const strokeIcons: Record<string, IconComponent> = {
  Add01Icon,
  AiChipIcon,
  Alert01Icon,
  AlertCircleIcon,
  Analytics01Icon,
  ArrowDown01Icon,
  ArrowDown02Icon,
  ArrowDownIcon,
  ArrowLeft01Icon,
  ArrowRight01Icon,
  ArrowUp01Icon,
  ArrowUp02Icon,
  ArrowUpRight01Icon,
  BarChartIcon,
  BookOpen01Icon,
  BrainIcon,
  BubbleChatAddIcon,
  BubbleChatIcon,
  Calendar03Icon,
  Call02Icon,
  Camera01Icon,
  Cancel01Icon,
  ChartLineData01Icon,
  ChartLineData02Icon,
  ChartRingIcon,
  CheckmarkCircle01Icon,
  CheckmarkCircle02Icon,
  CheckmarkSquare03Icon,
  Clock01Icon,
  Clock04Icon,
  CloudAngledRainIcon,
  CloudAngledZapIcon,
  CloudFastWindIcon,
  CloudIcon,
  CloudLittleRainIcon,
  CloudSnowIcon,
  CodeIcon,
  Comment01Icon,
  Contact01Icon,
  Copy01Icon,
  CpuIcon,
  CreditCardIcon,
  CustomerSupportIcon,
  Delete01Icon,
  Delete02Icon,
  DiscordIcon,
  DocumentAttachmentIcon,
  Download02Icon,
  Download04Icon,
  DropletIcon,
  Edit02Icon,
  FastWindIcon,
  FavouriteIcon,
  File01Icon,
  Flag02Icon,
  FlashIcon,
  Flowchart01Icon,
  FlowCircleIcon,
  FlowIcon,
  Folder02Icon,
  FolderIcon,
  Globe02Icon,
  GlobeIcon,
  HelpCircleIcon,
  Image01Icon,
  KeyboardIcon,
  LayoutGridIcon,
  LinkBackwardIcon,
  LinkSquare01Icon,
  LinkSquare02Icon,
  Loading03Icon,
  Location01Icon,
  Logout01Icon,
  MagicWand01Icon,
  Mail01Icon,
  MailOpen01Icon,
  MailSend01Icon,
  Menu01Icon,
  Message01Icon,
  MessageMultiple01Icon,
  MoreVerticalIcon,
  News01Icon,
  Notification01Icon,
  Notification02Icon,
  PencilEdit01Icon,
  PencilEdit02Icon,
  PieChart01Icon,
  Pin02Icon,
  PlayIcon,
  PlusSignIcon,
  RepeatIcon,
  Search01Icon,
  SentIcon,
  Settings01Icon,
  Settings02Icon,
  Share01Icon,
  Share08Icon,
  ShieldUserIcon,
  Sun03Icon,
  SunriseIcon,
  SunsetIcon,
  Tag01Icon,
  TelegramIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  Tick01Icon,
  Tick02Icon,
  ToggleOffIcon,
  ToggleOnIcon,
  Tornado02Icon,
  TranslationIcon,
  TwitterIcon,
  UploadCircle01Icon,
  UserCircle02Icon,
  UserCircleIcon,
  UserGroupIcon,
  UserIcon,
  UserSearch01Icon,
  WhatsappIcon,
  WorkflowSquare10Icon,
  Wrench01Icon,
};

// Extract paths from all icons
const iconPaths: Record<string, ExtractedSvgData> = {};

console.log("Extracting solid-rounded icons...");
for (const [name, component] of Object.entries(solidIcons)) {
  iconPaths[name] = extractSvgPaths(component, "solid");
  console.log(`  ${name}: ${iconPaths[name].paths.length} paths`);
}

console.log("\nExtracting stroke-rounded icons...");
for (const [name, component] of Object.entries(strokeIcons)) {
  iconPaths[name] = extractSvgPaths(component, "stroke");
  console.log(`  ${name}: ${iconPaths[name].paths.length} paths`);
}

console.log(`\nTotal icons extracted: ${Object.keys(iconPaths).length}`);

// Write to web config
const outputPath = path.join(
  __dirname,
  "../src/config/iconPaths.generated.json",
);
fs.writeFileSync(outputPath, JSON.stringify(iconPaths, null, 2));
console.log(`\nWrote icon paths to ${outputPath}`);

// Also write to shared lib (used by mobile)
const sharedOutputPath = path.join(
  __dirname,
  "../../../libs/shared/ts/src/icons/icon-paths.generated.json",
);
fs.mkdirSync(path.dirname(sharedOutputPath), { recursive: true });
fs.writeFileSync(sharedOutputPath, JSON.stringify(iconPaths, null, 2));
console.log(`Wrote icon paths to ${sharedOutputPath}`);

// Also output TypeScript file for type safety
const tsContent = `/**
 * Auto-generated file - DO NOT EDIT
 * Generated by: npx tsx apps/web/scripts/extract-icon-paths.ts
 */

export interface ExtractedSvgData {
  readonly viewBox: string;
  readonly paths: readonly string[];
}

export const iconPaths: Record<string, ExtractedSvgData> = ${JSON.stringify(iconPaths, null, 2)};

export function getIconPaths(iconName: string): ExtractedSvgData | null {
  return iconPaths[iconName] || null;
}
`;

const tsOutputPath = path.join(
  __dirname,
  "../src/config/iconPaths.generated.ts",
);
fs.writeFileSync(tsOutputPath, tsContent);
console.log(`Wrote TypeScript file to ${tsOutputPath}`);
