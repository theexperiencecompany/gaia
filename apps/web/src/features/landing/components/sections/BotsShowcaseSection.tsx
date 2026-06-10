"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import {
  ArrowLeft02Icon,
  ArrowRight02Icon,
  CircleArrowRight02Icon,
  SquareLockIcon,
} from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { Link } from "@/i18n/navigation";

import {
  ChatDemo,
  type ChatMessageItem,
  type ChatPlatform,
} from "../iphone/ChatDemo";
import { IPhoneMockup } from "../iphone/IPhoneMockup";
import {
  cascadeDurationMs,
  useStaggeredMessages as useStaggeredMessagesShared,
} from "../iphone/useStaggeredMessages";
import LargeHeader from "../shared/LargeHeader";

interface ActionLink {
  label: string;
  href: string;
  external?: boolean;
}

interface PhoneConfig {
  screenBackground?: string;
  statusBarTone?: "auto" | "light" | "dark";
}

interface DemoConfig {
  title?: string;
  subtitle?: string;
  messages: ChatMessageItem[];
}

interface Platform {
  id: ChatPlatform;
  name: string;
  icon: string | ReactNode;
  comingSoon?: boolean;
  primaryAction: ActionLink;
  phone: PhoneConfig;
  demo: DemoConfig;
}

const AVATAR_ARYAN = "/aryan-avatar.webp";

function IMessageChipIcon({ size = 20 }: { size?: number }) {
  return (
    // biome-ignore lint/a11y/noSvgWithoutTitle: decorative brand icon, hidden from a11y tree
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden>
      <rect width="20" height="20" rx="4.5" fill="#25D057" />
      <path
        d="M10 3.8C6.63 3.8 3.9 6.22 3.9 9.2c0 1.67.84 3.16 2.16 4.16-.04.58-.29 1.54-1.21 2.24 0 0 1.78.06 3.2-1.05.59.15 1.2.25 1.87.25 3.37 0 6.1-2.42 6.1-5.4S13.37 3.8 10 3.8z"
        fill="white"
      />
    </svg>
  );
}

const PLATFORMS: Platform[] = [
  {
    id: "whatsapp",
    name: "WhatsApp",
    icon: "/images/icons/macos/whatsapp.webp",
    primaryAction: {
      label: "Message on WhatsApp",
      href: "https://wa.me/12762088737",
      external: true,
    },
    phone: { screenBackground: "#F6F6F6" },
    demo: {
      title: "GAIA",
      messages: [
        {
          from: "me",
          text: "what's on my plate today?",
          time: "9:14",
          status: "read",
        },
        {
          from: "them",
          text: "4 meetings back to back from 9.30, plus that investor draft you flagged yesterday",
          time: "9:14",
        },
        {
          from: "them",
          text: "want me to push standup to 11 so you have a coffee window?",
          time: "9:14",
        },
        {
          from: "me",
          text: "yes pls. also remind me to call mom at 8 🙏",
          time: "9:15",
          status: "read",
        },
        {
          from: "them",
          text: "done & done 🫡",
          time: "9:15",
        },
      ],
    },
  },
  {
    id: "telegram",
    name: "Telegram",
    icon: "/images/icons/macos/telegram.webp",
    primaryAction: {
      label: "Message on Telegram",
      href: "https://t.me/heygaia_bot",
      external: true,
    },
    phone: { screenBackground: "#F6F6F6" },
    demo: {
      title: "GAIA",
      subtitle: "bot",
      messages: [
        {
          from: "me",
          text: "summarise my inbox",
          time: "14:02",
          status: "read",
        },
        {
          from: "them",
          text: "you've got 12 unread. 3 actually need you, the rest is noise",
          time: "14:03",
        },
        {
          from: "them",
          text: "drafting replies to the linear founder + the recruiter rn",
          time: "14:03",
        },
        {
          from: "me",
          text: "also book me to NYC next thursday",
          time: "14:04",
          status: "read",
        },
        {
          from: "them",
          text: "looking… delta has $189 out at 8am, lands 11ish. lock it in?",
          time: "14:04",
        },
      ],
    },
  },
  {
    id: "slack",
    name: "Slack",
    icon: "/images/icons/macos/slack.webp",
    primaryAction: {
      label: "Install in Slack",
      href: "/slack-bot",
    },
    phone: {},
    demo: {
      title: "design",
      subtitle: "42 members",
      messages: [
        {
          author: "Aryan",
          avatar: AVATAR_ARYAN,
          text: "@GAIA standup post for design? pull from yesterday's threads",
          time: "10:24 AM",
        },
        {
          author: "GAIA",
          text: "pulled this from 4 open PRs and 6 figma comments since yesterday 🧵",
          time: "10:24 AM",
          reactions: [
            { emoji: "🎉", count: 4 },
            { emoji: "🔥", count: 2 },
          ],
        },
        {
          author: "Aryan",
          avatar: AVATAR_ARYAN,
          text: "send it. also draft a reply to the PM thread in #product",
          time: "10:25 AM",
        },
        {
          author: "GAIA",
          text: "on it. DMing you the draft in 30s",
          time: "10:26 AM",
        },
      ],
    },
  },
  {
    id: "discord",
    name: "Discord",
    icon: "/images/icons/macos/discord.webp",
    primaryAction: {
      label: "Add to Your Server",
      href: "https://heygaia.io/discord-bot",
      external: true,
    },
    phone: { screenBackground: "#1E1F22", statusBarTone: "light" },
    demo: {
      title: "general",
      messages: [
        {
          author: "Aryan",
          avatar: AVATAR_ARYAN,
          authorColor: "#F47FFF",
          text: "@GAIA ship digest for the week?",
          time: "9:14 PM",
          reactions: [{ emoji: "👍", count: 3 }],
        },
        {
          author: "GAIA",
          authorColor: "#9CC3FF",
          text: "12 PRs merged, 4 features shipped, 2 incidents resolved 🚀",
          time: "9:14 PM",
        },
        {
          author: "Aryan",
          avatar: AVATAR_ARYAN,
          authorColor: "#F47FFF",
          text: "post it in #releases",
          time: "9:15 PM",
        },
        {
          author: "GAIA",
          authorColor: "#9CC3FF",
          text: "posted, ping me if anyone has follow-ups",
          time: "9:15 PM",
        },
      ],
    },
  },
  {
    id: "imessage",
    name: "iMessage",
    icon: <IMessageChipIcon />,
    comingSoon: true,
    primaryAction: { label: "Coming Soon", href: "" },
    phone: { screenBackground: "#FFFFFF" },
    demo: {
      title: "GAIA",
      messages: [
        {
          from: "me",
          text: "reschedule my 3pm to tomorrow same time",
          time: "2:58 PM",
          status: "read",
        },
        {
          from: "them",
          text: "done. rescheduled and invite updated",
        },
        {
          from: "me",
          text: "also add a note to call sarah before it",
          time: "3:04 PM",
          status: "read",
        },
        {
          from: "them",
          text: "added. anything else?",
        },
      ],
    },
  },
];

export default function BotsShowcaseSection() {
  const [activeId, setActiveId] = useState<ChatPlatform>(PLATFORMS[0].id);
  const [autoRotate, setAutoRotate] = useState(true);
  const active = PLATFORMS.find((p) => p.id === activeId) ?? PLATFORMS[0];

  const sectionRef = useRef<HTMLDivElement>(null);
  const inView = useSectionInView(sectionRef, 0.25);

  const visibleMessages = useStaggeredMessagesShared(
    active.demo.messages,
    inView,
  );
  const phoneRef = useRef<HTMLDivElement>(null);
  const isCtaFloating = useFloatingCta(phoneRef);

  const handleSelect = useCallback((id: ChatPlatform) => {
    setActiveId(id);
    setAutoRotate(false);
  }, []);

  const handlePrev = useCallback(() => {
    setAutoRotate(false);
    setActiveId((current) => {
      const idx = PLATFORMS.findIndex((p) => p.id === current);
      return PLATFORMS[(idx - 1 + PLATFORMS.length) % PLATFORMS.length].id;
    });
  }, []);

  const handleNext = useCallback(() => {
    setAutoRotate(false);
    setActiveId((current) => {
      const idx = PLATFORMS.findIndex((p) => p.id === current);
      return PLATFORMS[(idx + 1) % PLATFORMS.length].id;
    });
  }, []);

  useEffect(() => {
    if (inView) return;
    setAutoRotate(true);
  }, [inView]);

  useEffect(() => {
    if (!inView || !autoRotate) return;
    const cascadeMs = cascadeDurationMs(active.demo.messages.length);
    const dwellMs = 2500;
    const id = window.setTimeout(() => {
      setActiveId((current) => {
        const idx = PLATFORMS.findIndex((p) => p.id === current);
        return PLATFORMS[(idx + 1) % PLATFORMS.length].id;
      });
    }, cascadeMs + dwellMs);
    return () => window.clearTimeout(id);
  }, [inView, autoRotate, active]);

  return (
    <section
      ref={sectionRef}
      className="relative flex w-full flex-col items-center px-4 py-20 sm:px-6 sm:py-24 lg:px-8"
    >
      <div className="flex w-full max-w-6xl flex-col items-center gap-8">
        <LargeHeader
          chipText="Available everywhere"
          headingText="Reach GAIA from anywhere"
          subHeadingText="No new app to learn. Just open the one you already have open."
          centered
        />

        <PlatformChips
          platforms={PLATFORMS}
          activeId={activeId}
          onSelect={handleSelect}
        />

        <div ref={phoneRef}>
          <PhoneFrame platform={active} messages={visibleMessages} />
        </div>

        <FloatingCTA
          isFloating={isCtaFloating}
          action={active.primaryAction}
          actionKey={active.id}
          iconSrc={typeof active.icon === "string" ? active.icon : undefined}
          comingSoon={active.comingSoon}
          onPrev={handlePrev}
          onNext={handleNext}
        />
      </div>
    </section>
  );
}

function useSectionInView(
  ref: React.RefObject<HTMLElement | null>,
  threshold: number,
): boolean {
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") {
      setInView(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => setInView(entry?.isIntersecting ?? false),
      { threshold },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref, threshold]);

  return inView;
}

function FloatingCTA({
  isFloating,
  action,
  actionKey,
  iconSrc,
  comingSoon,
  onPrev,
  onNext,
}: {
  isFloating: boolean;
  action: ActionLink;
  actionKey: string;
  iconSrc: string | undefined;
  comingSoon?: boolean;
  onPrev: () => void;
  onNext: () => void;
}) {
  // Reserve the static-flow slot so the layout never jumps when the button
  // pops out of the flow into a fixed position. The CTA is rendered twice:
  //   - In flow, invisible while floating (reserves space)
  //   - Fixed at the bottom while floating, fades in via opacity only
  return (
    <div className="relative flex w-full justify-center pt-2">
      <div
        aria-hidden={isFloating}
        className={isFloating ? "pointer-events-none opacity-0" : "opacity-100"}
      >
        <CTAGroup
          actionKey={actionKey}
          action={action}
          iconSrc={iconSrc}
          comingSoon={comingSoon}
          onPrev={onPrev}
          onNext={onNext}
        />
      </div>

      <AnimatePresence initial={false}>
        {isFloating && (
          <m.div
            key="floating"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="pointer-events-none fixed inset-x-0 bottom-6 z-[1001] flex justify-center px-4"
          >
            <div className="pointer-events-auto">
              <CTAGroup
                actionKey={actionKey}
                action={action}
                iconSrc={iconSrc}
                comingSoon={comingSoon}
                onPrev={onPrev}
                onNext={onNext}
              />
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function CTAGroup({
  actionKey,
  action,
  iconSrc,
  comingSoon,
  onPrev,
  onNext,
}: {
  actionKey: string;
  action: ActionLink;
  iconSrc: string | undefined;
  comingSoon?: boolean;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="relative flex w-[390px] max-w-full items-center justify-center sm:w-[429px]">
      <div className="-left-24 -translate-y-1/2 absolute top-1/2 flex items-center gap-2">
        <Button
          isIconOnly
          variant="flat"
          radius="full"
          aria-label="Previous platform"
          onPress={onPrev}
          className="min-w-10 h-10 w-10 p-0 text-zinc-500 transition-colors hover:text-zinc-200"
        >
          <ArrowLeft02Icon size={24} />
        </Button>
        <Button
          isIconOnly
          variant="flat"
          radius="full"
          aria-label="Next platform"
          onPress={onNext}
          className="min-w-10 h-10 w-10 p-0 text-zinc-500 transition-colors hover:text-zinc-200"
        >
          <ArrowRight02Icon size={24} />
        </Button>
      </div>
      <PlatformCTASwitcher
        actionKey={actionKey}
        action={action}
        iconSrc={iconSrc}
        comingSoon={comingSoon}
      />
    </div>
  );
}

function PlatformCTASwitcher({
  actionKey,
  action,
  iconSrc,
  comingSoon,
}: {
  actionKey: string;
  action: ActionLink;
  iconSrc: string | undefined;
  comingSoon?: boolean;
}) {
  return (
    <AnimatePresence mode="wait" initial={false}>
      <m.div
        key={actionKey}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.18, ease: "easeOut" }}
      >
        <PrimaryCTA action={action} iconSrc={iconSrc} comingSoon={comingSoon} />
      </m.div>
    </AnimatePresence>
  );
}

function useFloatingCta(
  phoneRef: React.RefObject<HTMLDivElement | null>,
): boolean {
  const [floating, setFloating] = useState(false);

  useEffect(() => {
    const phone = phoneRef.current;
    if (!phone) return;

    const update = (): void => {
      const phoneRect = phone.getBoundingClientRect();
      const vh = window.innerHeight;
      // Threshold is tuned so the floating button and its static-flow slot
      // line up vertically at the moment of switch — the visual position
      // doesn't jump.
      const phoneEnoughVisible = phoneRect.top < vh - 200;
      // The floating button sits at vh - 56 (bottom-6 + button height). The
      // static slot sits at phoneRect.bottom + 62 (flex gap-8 + pt-2 + half
      // button). The switch happens when the two y positions match.
      const phoneStillNearBottom = phoneRect.bottom > vh - 118;
      setFloating(phoneEnoughVisible && phoneStillNearBottom);
    };

    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [phoneRef]);

  return floating;
}

function PlatformChips({
  platforms,
  activeId,
  onSelect,
}: {
  platforms: Platform[];
  activeId: ChatPlatform;
  onSelect: (id: ChatPlatform) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Choose a platform"
      className="flex flex-wrap items-center justify-center gap-2"
    >
      {platforms.map((p) => {
        const isActive = p.id === activeId;
        return (
          <Chip
            key={p.id}
            variant={isActive ? "solid" : "flat"}
            color={isActive ? "primary" : "default"}
            size="lg"
            role="tab"
            aria-selected={isActive}
            onClick={() => onSelect(p.id)}
            className="cursor-pointer select-none"
            startContent={
              typeof p.icon === "string" ? (
                <Image
                  src={p.icon}
                  alt=""
                  width={20}
                  height={20}
                  className="h-5 w-5 shrink-0 rounded"
                  aria-hidden
                />
              ) : (
                <span
                  className="flex h-5 w-5 shrink-0 items-center justify-center"
                  aria-hidden
                >
                  {p.icon}
                </span>
              )
            }
          >
            {p.name}
          </Chip>
        );
      })}
    </div>
  );
}

function PhoneFrame({
  platform,
  messages,
}: {
  platform: Platform;
  messages: ChatMessageItem[];
}) {
  return (
    <div className="relative isolate sm:pb-[82px]">
      <div
        aria-hidden
        className="-z-10 pointer-events-none absolute -inset-x-[28rem] -inset-y-[20rem]"
        style={{
          backgroundImage:
            "radial-gradient(closest-side, rgba(0,187,255,0.7), rgba(0,187,255,0.25) 35%, rgba(0,187,255,0.06) 65%, transparent 80%)",
          filter: "blur(18px)",
        }}
      />
      <IPhoneMockup
        screenBackground={platform.phone.screenBackground}
        statusBarTone={platform.phone.statusBarTone}
        className="sm:scale-[1.1] sm:origin-top"
      >
        <AnimatePresence mode="wait" initial={false}>
          <m.div
            key={platform.id}
            className="flex h-full flex-col"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
          >
            <ChatDemo
              platform={platform.id}
              title={platform.demo.title}
              subtitle={platform.demo.subtitle}
              messages={messages}
            />
          </m.div>
        </AnimatePresence>
      </IPhoneMockup>
    </div>
  );
}

function PrimaryCTA({
  action,
  iconSrc,
  comingSoon,
}: {
  action: ActionLink;
  iconSrc: string | undefined;
  comingSoon?: boolean;
}) {
  if (comingSoon) {
    return (
      <RaisedButton
        color="#52525B"
        className="h-10 cursor-not-allowed rounded-full pr-4 pl-3 before:rounded-full"
        tabIndex={-1}
        aria-disabled="true"
        onClick={(e) => e.preventDefault()}
      >
        <span className="flex items-center gap-2">
          <SquareLockIcon size={18} />
          Coming Soon
        </span>
      </RaisedButton>
    );
  }

  const buttonContent = (
    <span className="flex items-center gap-2">
      {iconSrc && (
        <Image
          src={iconSrc}
          alt=""
          width={28}
          height={28}
          aria-hidden
          className="h-7 w-7 shrink-0 rounded"
        />
      )}
      {action.label}
      <CircleArrowRight02Icon size={18} />
    </span>
  );

  if (action.external) {
    return (
      <RaisedButton
        color="#00bbff"
        className="text-black! h-10 rounded-full pr-4 pl-1.5 before:rounded-full"
        onClick={() =>
          window.open(action.href, "_blank", "noopener,noreferrer")
        }
      >
        {buttonContent}
      </RaisedButton>
    );
  }

  return (
    <Link href={action.href}>
      <RaisedButton
        color="#00bbff"
        className="text-black! h-10 rounded-full pr-4 pl-1.5 before:rounded-full"
      >
        {buttonContent}
      </RaisedButton>
    </Link>
  );
}
