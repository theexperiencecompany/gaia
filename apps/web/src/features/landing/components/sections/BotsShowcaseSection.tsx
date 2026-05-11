"use client";

import { Chip } from "@heroui/chip";
import { CircleArrowRight02Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import { useEffect, useMemo, useRef, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { Link } from "@/i18n/navigation";

import {
  ChatDemo,
  type ChatMessageItem,
  type ChatPlatform,
} from "../iphone/ChatDemo";
import { IPhoneMockup } from "../iphone/IPhoneMockup";
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
  icon: string;
  primaryAction: ActionLink;
  phone: PhoneConfig;
  demo: DemoConfig;
}

const AVATAR_ARYAN = "/aryan-avatar.webp";

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
];

export default function BotsShowcaseSection() {
  const [activeId, setActiveId] = useState<ChatPlatform>(PLATFORMS[0].id);
  const active = PLATFORMS.find((p) => p.id === activeId) ?? PLATFORMS[0];
  const visibleMessages = useStaggeredMessages(active);
  const phoneRef = useRef<HTMLDivElement>(null);
  const isCtaFloating = useFloatingCta(phoneRef);

  return (
    <section className="relative flex w-full flex-col items-center px-4 py-20 sm:px-6 sm:py-24 lg:px-8">
      <div className="flex w-full max-w-6xl flex-col items-center gap-8">
        <LargeHeader headingText="Reach GAIA from anywhere" centered />

        <PlatformChips
          platforms={PLATFORMS}
          activeId={activeId}
          onSelect={setActiveId}
        />

        <div ref={phoneRef}>
          <PhoneFrame platform={active} messages={visibleMessages} />
        </div>

        <FloatingCTA
          isFloating={isCtaFloating}
          action={active.primaryAction}
          actionKey={active.id}
          iconSrc={active.icon}
        />
      </div>
    </section>
  );
}

function FloatingCTA({
  isFloating,
  action,
  actionKey,
  iconSrc,
}: {
  isFloating: boolean;
  action: ActionLink;
  actionKey: string;
  iconSrc: string;
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
        <PlatformCTASwitcher
          actionKey={actionKey}
          action={action}
          iconSrc={iconSrc}
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
              <PlatformCTASwitcher
                actionKey={actionKey}
                action={action}
                iconSrc={iconSrc}
              />
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function PlatformCTASwitcher({
  actionKey,
  action,
  iconSrc,
}: {
  actionKey: string;
  action: ActionLink;
  iconSrc: string;
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
        <PrimaryCTA action={action} iconSrc={iconSrc} />
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

const TYPING_DELAY_MS = 450;
const TYPING_DURATION_MS = 850;

function useStaggeredMessages(platform: Platform): ChatMessageItem[] {
  const allMessages = platform.demo.messages;
  const [visibleCount, setVisibleCount] = useState(1);
  const [showTyping, setShowTyping] = useState(false);

  useEffect(() => {
    setVisibleCount(1);
    setShowTyping(false);
    if (allMessages.length <= 1) return;

    const timers: ReturnType<typeof setTimeout>[] = [];
    let elapsed = 0;
    for (let i = 1; i < allMessages.length; i++) {
      elapsed += TYPING_DELAY_MS;
      timers.push(setTimeout(() => setShowTyping(true), elapsed));
      elapsed += TYPING_DURATION_MS;
      timers.push(
        setTimeout(() => {
          setShowTyping(false);
          setVisibleCount((c) => c + 1);
        }, elapsed),
      );
    }

    return () => {
      for (const t of timers) clearTimeout(t);
    };
  }, [allMessages]);

  return useMemo(() => {
    const real = allMessages.slice(0, visibleCount).map((m, i) => ({
      ...m,
      id: m.id ?? `msg-${i}`,
    }));
    if (!showTyping || visibleCount >= allMessages.length) return real;
    const next = allMessages[visibleCount];
    return [
      ...real,
      {
        id: `typing-${visibleCount}`,
        from: next.from,
        author: next.author,
        avatar: next.avatar,
        authorColor: next.authorColor,
        typing: true,
      },
    ];
  }, [allMessages, visibleCount, showTyping]);
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
              <Image
                src={p.icon}
                alt=""
                width={20}
                height={20}
                className="h-5 w-5 shrink-0 rounded"
                aria-hidden
              />
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
    <div className="relative isolate">
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
}: {
  action: ActionLink;
  iconSrc: string;
}) {
  const button = (
    <RaisedButton
      color="#00bbff"
      className="text-black! h-10 rounded-full pr-4 pl-1.5 before:rounded-full"
    >
      <span className="flex items-center gap-2">
        <Image
          src={iconSrc}
          alt=""
          width={28}
          height={28}
          aria-hidden
          className="h-7 w-7 shrink-0 rounded"
        />
        {action.label}
        <CircleArrowRight02Icon size={18} />
      </span>
    </RaisedButton>
  );

  if (action.external) {
    return (
      <a href={action.href} target="_blank" rel="noreferrer">
        {button}
      </a>
    );
  }

  return <Link href={action.href}>{button}</Link>;
}
