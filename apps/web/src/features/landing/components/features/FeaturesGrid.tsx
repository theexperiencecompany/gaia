"use client";

import {
  AiChipIcon,
  AlarmClockIcon,
  Analytics01Icon,
  ArrowRight01Icon,
  BarChartIcon,
  BookOpen01Icon,
  Brain02Icon,
  BrainIcon,
  BubbleChatAddIcon,
  BubbleChatIcon,
  Calendar03Icon,
  Call02Icon,
  ChartLineData01Icon,
  CheckListIcon,
  CheckmarkCircle01Icon,
  Clock01Icon,
  CodeIcon,
  ComputerTerminal01Icon,
  ConnectIcon,
  Contact01Icon,
  Copy01Icon,
  DiscordIcon,
  DocumentAttachmentIcon,
  Download02Icon,
  Edit02Icon,
  FavouriteIcon,
  File01Icon,
  FlashIcon,
  FlowCircleIcon,
  Flowchart01Icon,
  FlowIcon,
  Globe02Icon,
  GlobeIcon,
  Image01Icon,
  KeyboardIcon,
  LayoutGridIcon,
  LinkSquare01Icon,
  MagicWand01Icon,
  Mail01Icon,
  MessageMultiple01Icon,
  NotificationIcon,
  PackageOpenIcon,
  PencilEdit01Icon,
  Pin02Icon,
  PlayIcon,
  PuzzleIcon,
  RepeatIcon,
  Search01Icon,
  Share01Icon,
  ShieldUserIcon,
  SourceCodeCircleIcon,
  Tag01Icon,
  Target02Icon,
  TelegramIcon,
  ToolsIcon,
  UserCircleIcon,
  UserGroupIcon,
  UserSearch01Icon,
  WorkflowCircle06Icon,
  WorkflowSquare10Icon,
  Wrench01Icon,
  ZapIcon,
} from "@icons";
import type { Easing, Variants } from "motion/react";
import { m } from "motion/react";
import Link from "next/link";
import type { ComponentType } from "react";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import LargeHeader from "@/features/landing/components/shared/LargeHeader";
import {
  FEATURE_CATEGORIES,
  getFeaturesByCategory,
} from "@/features/landing/data/featuresData";

interface IconProps {
  size?: number;
  color?: string;
  className?: string;
}

const ICON_MAP: Record<string, ComponentType<IconProps>> = {
  // Used as feature.icon values in featuresData
  BubbleChatIcon,
  Search01Icon,
  BrainIcon,
  Notification01Icon: NotificationIcon,
  Notification02Icon: NotificationIcon,
  Image01Icon,
  ComputerTerminal01Icon,
  SourceCodeSquareIcon: SourceCodeCircleIcon,
  LayoutGridIcon,
  CheckListIcon,
  Calendar02Icon: Calendar03Icon,
  Calendar03Icon,
  Mail01Icon,
  Target02Icon,
  AlarmClockIcon,
  Pin02Icon,
  DashboardSquare03Icon: LayoutGridIcon,
  WorkflowSquare10Icon,
  WorkflowCircle06Icon,
  Clock01Icon,
  LightningIcon: FlashIcon,
  FlashIcon,
  FileEditIcon: DocumentAttachmentIcon,
  DocumentAttachmentIcon,
  PackageIcon: PackageOpenIcon,
  PackageOpenIcon,
  IntegrationIcon: ConnectIcon,
  ConnectIcon,
  Store01Icon: Globe02Icon,
  Globe02Icon,
  ServerIcon: SourceCodeCircleIcon,
  SourceCodeCircleIcon,
  PuzzlePieceIcon: PuzzleIcon,
  PuzzleIcon,
  UserCircleIcon,
  BotIcon: UserGroupIcon,
  UserGroupIcon,
  Wrench01Icon,
  CustomIntegrationIcon: Wrench01Icon,
  MicrophoneIcon: Call02Icon,
  Call02Icon,
  MessageMultiple02Icon: MessageMultiple01Icon,
  MessageMultiple01Icon,
  GameboyIcon: DiscordIcon,
  DiscordIcon,
  AirplaneIcon: TelegramIcon,
  TelegramIcon,
  SmartPhone01Icon: BubbleChatIcon,
  // Benefit icons
  ZapIcon,
  FlowIcon,
  Brain02Icon,
  ChartLineData01Icon,
  BubbleChatAddIcon,
  ShieldUserIcon,
  UserSearch01Icon,
  MagicWand01Icon,
  PencilEdit01Icon,
  CodeIcon,
  BarChartIcon,
  ChartRingIcon: BarChartIcon,
  Analytics01Icon,
  AiChipIcon,
  CheckmarkCircle01Icon,
  RepeatIcon,
  GlobeIcon,
  FavouriteIcon,
  LinkSquare01Icon,
  LinkSquare02Icon: LinkSquare01Icon,
  Copy01Icon,
  Share01Icon,
  ToolsIcon,
  File01Icon,
  Download02Icon,
  BookOpen01Icon,
  FlowCircleIcon,
  Flowchart01Icon,
  KeyboardIcon,
  Tag01Icon,
  Edit02Icon,
  PlayIcon,
  Contact01Icon,
};

interface FeatureIconProps {
  name: string;
}

function FeatureIcon({ name }: FeatureIconProps) {
  const Icon = ICON_MAP[name];
  if (!Icon) {
    const FallbackIcon = ZapIcon;
    return <FallbackIcon size={18} color="#00bbff" />;
  }
  return <Icon size={18} color="#00bbff" />;
}

const EASE_OUT: Easing = "easeOut";

const containerVariants: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.05 } },
};

const cardVariants: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.4, ease: EASE_OUT },
  },
};

export function FeaturesGrid() {
  return (
    <LazyMotionProvider>
      <div className="min-h-screen bg-[#111111]">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="flex justify-center mb-12">
            <LargeHeader
              chipText="Features"
              headingText="Everything GAIA can do"
              subHeadingText="30 capabilities across AI, productivity, automation, integrations, and every platform you use."
              centered
            />
          </div>

          {FEATURE_CATEGORIES.map((category) => {
            const features = getFeaturesByCategory(category);
            return (
              <section key={category} className="mb-16">
                <p className="mb-4 mt-12 text-xs font-medium uppercase tracking-widest text-[#00bbff]">
                  {category}
                </p>
                <m.div
                  className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3"
                  variants={containerVariants}
                  initial="hidden"
                  whileInView="visible"
                  viewport={{ once: true, margin: "-50px" }}
                >
                  {features.map((feature) => (
                    <m.div key={feature.slug} variants={cardVariants}>
                      <Link
                        href={`/features/${feature.slug}`}
                        className="block rounded-2xl bg-zinc-800/50 p-5 transition-colors hover:bg-zinc-800"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#00bbff]/10">
                            <FeatureIcon name={feature.icon} />
                          </div>
                          <ArrowRight01Icon
                            size={16}
                            className="text-zinc-500"
                          />
                        </div>
                        <p className="mt-3 text-sm font-medium text-zinc-100">
                          {feature.title}
                        </p>
                        <p className="mt-1 text-xs font-light leading-relaxed text-zinc-400">
                          {feature.tagline}
                        </p>
                      </Link>
                    </m.div>
                  ))}
                </m.div>
              </section>
            );
          })}

          <div className="mt-16 flex flex-col items-center gap-4 pb-16 text-center">
            <p className="text-lg font-light text-zinc-300">
              Start using GAIA free
            </p>
            <GetStartedButton />
          </div>
        </div>
      </div>
    </LazyMotionProvider>
  );
}
