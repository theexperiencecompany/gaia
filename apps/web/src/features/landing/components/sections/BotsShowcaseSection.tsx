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
  type ActionLink,
  PLATFORMS,
  type Platform,
} from "../iphone/platformDemos";
import {
  cascadeDurationMs,
  useStaggeredMessages as useStaggeredMessagesShared,
} from "../iphone/useStaggeredMessages";
import LargeHeader from "../shared/LargeHeader";

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
