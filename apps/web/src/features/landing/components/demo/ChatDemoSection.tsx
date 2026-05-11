"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import {
  Copy01Icon,
  LinkBackwardIcon,
  Login02Icon,
  PinIcon,
  RedoIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import Link from "next/link";
import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { ChevronRight } from "@/components/shared/icons";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { RaisedButton } from "@/components/ui/raised-button";
import { appConfig } from "@/config/appConfig";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import DummyComposer from "@/features/landing/components/demo/DummyComposer";
import { cn } from "@/lib/utils";
import DemoCalendarView from "./calendar-demo/DemoCalendarView";
import DemoChatHeader from "./DemoChatHeader";
import { DemoFinalCard } from "./DemoFinalCards";
import DemoNotificationsPopover from "./DemoNotificationsPopover";
import DemoSidebar from "./DemoSidebar";
import DemoToolCalls from "./DemoToolCalls";
import DemoDashboardView from "./dashboard-demo/DemoDashboardView";
import { BASE_TIMINGS, slideUp, tx, USE_CASES } from "./demoConstants";
import DemoGoalsView from "./goals-demo/DemoGoalsView";
import DemoIntegrationsView from "./integrations-demo/DemoIntegrationsView";
import MiniWaveSpinner from "./MiniWaveSpinner";
import DemoTodosView from "./todos-demo/DemoTodosView";
import type { DemoPage, Phase } from "./types";
import DemoWorkflowsView from "./workflows-demo/DemoWorkflowsView";

type TypingTextProps = {
  text: string;
  isTyping: boolean;
};

type TypingTextHandle = {
  setTypedText: (value: string) => void;
};

const TypingText = memo(
  forwardRef<TypingTextHandle, TypingTextProps>(function TypingText(
    { text, isTyping },
    ref,
  ) {
    const [typedText, setTypedText] = useState(() => (isTyping ? "" : text));

    useImperativeHandle(
      ref,
      () => ({
        setTypedText,
      }),
      [],
    );

    useEffect(() => {
      if (!isTyping) setTypedText(text);
    }, [isTyping, text]);

    const displayText = isTyping ? typedText : text;

    return (
      <>
        {displayText}
        {isTyping && (
          <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse bg-white/60 align-middle" />
        )}
      </>
    );
  }),
);

const MemoDemoSidebar = memo(DemoSidebar);
const MemoDemoToolCalls = memo(DemoToolCalls);
const MemoDemoFinalCard = memo(DemoFinalCard);
const MemoDemoChatHeader = memo(DemoChatHeader);
const MemoDemoNotificationsPopover = memo(DemoNotificationsPopover);
const MemoDemoDashboardView = memo(DemoDashboardView);
const MemoDemoCalendarView = memo(DemoCalendarView);
const MemoDemoWorkflowsView = memo(DemoWorkflowsView);
const MemoDemoGoalsView = memo(DemoGoalsView);
const MemoDemoIntegrationsView = memo(DemoIntegrationsView);
const MemoDemoTodosView = memo(DemoTodosView);

const UserAvatar = memo(function UserAvatar() {
  return (
    <Avatar className="relative bottom-18 rounded-full border border-white/10 bg-black">
      <AvatarImage
        src="https://avatars.githubusercontent.com/u/64796509?v=3&s=56"
        alt="User"
        loading="lazy"
        decoding="async"
      />
      <AvatarFallback className="bg-primary/20 text-xs font-medium text-primary">
        U
      </AvatarFallback>
    </Avatar>
  );
});

const AryanAvatar = memo(function AryanAvatar() {
  return (
    <Avatar className="relative bottom-18 rounded-full border border-white/10 bg-black">
      <AvatarImage
        src="https://avatars.githubusercontent.com/u/64796509?v=3&s=56"
        alt="Aryan"
        loading="lazy"
        decoding="async"
      />
      <AvatarFallback className="bg-primary/20 text-xs font-medium text-primary">
        AR
      </AvatarFallback>
    </Avatar>
  );
});

const GaiaLogo = memo(function GaiaLogo({
  className,
  priority,
}: {
  className?: string;
  priority?: boolean;
}) {
  return (
    <Image
      src="/images/logos/logo.webp"
      width={28}
      height={28}
      loading={priority ? "eager" : "lazy"}
      priority={priority}
      sizes="28px"
      alt="GAIA"
      className={className}
    />
  );
});

const OgImage = memo(function OgImage() {
  return (
    <Image
      src="/og-image.webp"
      alt="GAIA"
      width={460}
      height={194}
      priority
      loading="eager"
      sizes="(min-width: 640px) 460px, 90vw"
      className="rounded-xl object-cover aspect-video"
    />
  );
});

export default function ChatDemoSection() {
  const [activePage, setActivePage] = useState<DemoPage>("chats");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [selectedIntegrationId, setSelectedIntegrationId] = useState<
    string | null
  >(null);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [activeUseCase, setActiveUseCase] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [loadingText, setLoadingText] = useState("GAIA is thinking...");
  const [loadingKey, setLoadingKey] = useState(0);
  const [loadingCat, setLoadingCat] = useState<string | undefined>();
  const [isInView, setIsInView] = useState(false);
  const [toolsExpanded, setToolsExpanded] = useState(false);
  const [customUserMessage, setCustomUserMessage] = useState("");
  const timers = useRef<
    Array<ReturnType<typeof setTimeout> | ReturnType<typeof setInterval>>
  >([]);
  const messagesRef = useRef<HTMLDivElement>(null);
  const activeCaseRef = useRef(0);
  const typingTextRef = useRef<TypingTextHandle>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const phaseRef = useRef<Phase>(phase);

  const clearAll = useCallback(() => {
    for (const t of timers.current) {
      clearTimeout(t);
      clearInterval(t);
    }
    timers.current = [];
  }, []);

  const add = useCallback((fn: () => void, delay: number) => {
    timers.current.push(setTimeout(fn, delay));
  }, []);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      if (messagesRef.current)
        messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    });
  }, []);

  const runAnimation = useCallback(
    (ucIndex: number) => {
      const useCase = USE_CASES[ucIndex];
      const T = BASE_TIMINGS;

      clearAll();
      setPhase("idle");
      setLoadingText("GAIA is thinking...");
      setLoadingKey(0);
      setLoadingCat(undefined);
      setToolsExpanded(false);
      typingTextRef.current?.setTypedText("");

      add(() => {
        setPhase("user_sent");
        scrollToBottom();
      }, T.userMsg);

      add(() => {
        setPhase("thinking");
        setLoadingText(useCase.loadingTexts[0]);
        setLoadingKey((k) => k + 1);
        setLoadingCat(undefined);
        scrollToBottom();
      }, T.thinking);

      add(() => {
        setPhase("loading1");
        setLoadingText(useCase.loadingTexts[1]);
        setLoadingKey((k) => k + 1);
        setLoadingCat(useCase.tools[2]?.category);
      }, T.loading1);

      add(() => {
        setPhase("loading2");
        setLoadingText(useCase.loadingTexts[2]);
        setLoadingKey((k) => k + 1);
        setLoadingCat(useCase.tools[3]?.category);
      }, T.loading2);

      add(() => setPhase("tool_calls"), T.toolCalls);

      add(() => {
        setPhase("responding");
        const response = useCase.botResponse;
        let i = 0;
        const tick = setInterval(() => {
          i += 3;
          typingTextRef.current?.setTypedText(response.slice(0, i));
          if (i >= response.length) {
            clearInterval(tick);
            typingTextRef.current?.setTypedText(response);
          }
        }, 18);
        timers.current.push(tick);
      }, T.botResponse);

      add(() => {
        setPhase("final_card");
        scrollToBottom();
      }, T.finalCard);

      add(() => setPhase("done"), T.done);

      // Auto-advance to next use case after holding the end state
      add(() => {
        const next = (ucIndex + 1) % USE_CASES.length;
        activeCaseRef.current = next;
        setActiveUseCase(next);
        runAnimation(next);
      }, T.loop);
    },
    [add, clearAll, scrollToBottom],
  );

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        const visible = entry.isIntersecting;
        setIsInView(visible);
        if (activePage === "chats") {
          if (visible) {
            runAnimation(activeCaseRef.current);
          } else {
            clearAll();
          }
        }
      },
      { threshold: 0.2 },
    );

    observer.observe(node);

    return () => {
      observer.disconnect();
      clearAll();
    };
  }, [activePage, clearAll, runAnimation]);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  useEffect(() => {
    setSidebarOpen(window.innerWidth >= 768);
  }, []);

  const switchUseCase = useCallback(
    (idx: number) => {
      activeCaseRef.current = idx;
      setActiveUseCase(idx);
      runAnimation(idx);
    },
    [runAnimation],
  );

  const handleUserSend = useCallback(
    (message: string) => {
      clearAll();
      setCustomUserMessage(message);
      setPhase("cta");
      scrollToBottom();
    },
    [clearAll, scrollToBottom],
  );

  const handleIntegrationSelect = useCallback((id: string) => {
    setSelectedIntegrationId(id);
    setActivePage("integrations");
  }, []);

  const handlePageChange = useCallback(
    (page: DemoPage) => {
      setActivePage(page);
      if (page !== "integrations") setSelectedIntegrationId(null);
      if (page !== "chats") {
        clearAll();
      } else if (phaseRef.current === "idle") {
        runAnimation(activeCaseRef.current);
      }
    },
    [clearAll, runAnimation],
  );

  const handleToggleSidebar = useCallback(() => {
    setSidebarOpen((o) => !o);
  }, []);

  const handleNotificationsClick = useCallback(() => {
    setNotificationsOpen((o) => !o);
  }, []);

  const handleNotificationsClose = useCallback(() => {
    setNotificationsOpen(false);
  }, []);

  const handleIntegrationsSelectionChange = useCallback((id: string | null) => {
    setSelectedIntegrationId(id);
  }, []);

  const handleToolsToggle = useCallback(() => {
    setToolsExpanded((e) => !e);
  }, []);

  const handleRetry = useCallback(() => {
    switchUseCase(activeUseCase);
  }, [activeUseCase, switchUseCase]);

  const uc = USE_CASES[activeUseCase];

  const showUser = phase !== "idle" && phase !== "cta";
  const showLoading = ["thinking", "loading1", "loading2"].includes(phase);
  const showTools = ["tool_calls", "responding", "final_card", "done"].includes(
    phase,
  );
  const showResponse = ["responding", "final_card", "done"].includes(phase);
  const showFinalCard = ["final_card", "done"].includes(phase);
  const showBotLogo = showTools || showResponse;
  const toolIcon = useMemo(
    () =>
      loadingCat
        ? getToolCategoryIcon(loadingCat, {
            size: 18,
            width: 18,
            height: 18,
            iconOnly: true,
            pulsating: true,
          })
        : null,
    [loadingCat],
  );

  const activePageContent = (() => {
    switch (activePage) {
      case "dashboard":
        return (
          <div className="flex-1 overflow-y-auto">
            <MemoDemoDashboardView />
          </div>
        );
      case "calendar":
        return (
          <div className="flex flex-1 overflow-hidden">
            <MemoDemoCalendarView />
          </div>
        );
      case "workflows":
        return (
          <div className="flex-1 overflow-y-auto">
            <MemoDemoWorkflowsView />
          </div>
        );
      case "goals":
        return (
          <div className="flex flex-1 overflow-hidden">
            <MemoDemoGoalsView />
          </div>
        );
      case "integrations":
        return (
          <div className="flex flex-1 overflow-hidden">
            <MemoDemoIntegrationsView
              externalSelectedId={selectedIntegrationId}
              onSelectionChange={handleIntegrationsSelectionChange}
            />
          </div>
        );
      case "todos":
        return (
          <div className="flex flex-1 overflow-hidden">
            <MemoDemoTodosView />
          </div>
        );
      default:
        return null;
    }
  })();

  return (
    <div
      ref={containerRef}
      className="relative flex w-full flex-col items-center"
    >
      <div
        className={`mb-4 text-center ${isInView ? "animate-in fade-in slide-in-from-bottom-4 duration-[400ms]" : "opacity-0"}`}
      >
        <p className="mb-2 text-sm uppercase tracking-widest text-primary">
          See it in action
        </p>
        <h2 className="text-5xl sm:text-6xl font-serif tracking-tight text-white font-normal">
          Your GAIA, actually working
        </h2>
      </div>

      {/* Demo window */}
      <div
        className={cn(
          "overflow-hidden rounded-3xl h-[600px] sm:h-[720px] w-[95vw] sm:w-[85vw]",
          isInView
            ? "animate-in fade-in slide-in-from-bottom-6 zoom-in-95 duration-500"
            : "opacity-0",
        )}
        style={
          {
            "--color-primary-bg": "#111111",
          } as React.CSSProperties
        }
      >
        <div
          className="flex h-9 shrink-0 items-center gap-1.5 px-4"
          style={{ backgroundColor: "#1a1a1a" }}
        >
          <div className="h-3 w-3 cursor-pointer rounded-full bg-zinc-700 transition-colors hover:bg-red-500" />
          <div className="h-3 w-3 cursor-pointer rounded-full bg-zinc-700 transition-colors hover:bg-yellow-400" />
          <div className="h-3 w-3 cursor-pointer rounded-full bg-zinc-700 transition-colors hover:bg-green-500" />
          <div className="flex justify-center flex-1">
            <a
              className="ml-4 text-center text-[11px] text-zinc-500 hover:text-primary w-fit"
              target="_blank"
              rel="noopener noreferrer"
              href={appConfig.site.domain}
            >
              {appConfig.site.name} — {appConfig.site.domain}
            </a>
          </div>
        </div>
        <div className="flex h-full" style={{ height: "calc(100% - 36px)" }}>
          <MemoDemoSidebar
            open={sidebarOpen}
            activePage={activePage}
            selectedIntegrationId={selectedIntegrationId}
            onIntegrationSelect={handleIntegrationSelect}
            onPageChange={handlePageChange}
          />

          <div
            className="relative flex min-w-0 flex-1 flex-col"
            style={{ backgroundColor: "#111111" }}
          >
            <MemoDemoChatHeader
              sidebarOpen={sidebarOpen}
              activePage={activePage}
              onToggleSidebar={handleToggleSidebar}
              onNotificationsClick={handleNotificationsClick}
            />

            <MemoDemoNotificationsPopover
              open={notificationsOpen}
              onClose={handleNotificationsClose}
            />

            {activePageContent}

            {activePage === "chats" && (
              <>
                {/* Messages — slightly narrower than full for visual breathing room */}
                <div
                  ref={messagesRef}
                  className="flex-1 overflow-y-auto px-4 py-3"
                >
                  <div className="mx-auto w-full max-w-2xl">
                    {/* CTA state — shown when user sends a real message */}
                    {phase === "cta" && (
                      <div
                        key="cta-view"
                        className="flex flex-col animate-in fade-in duration-300"
                      >
                        {/* User message bubble */}
                        <div className="mb-2 flex w-full items-end justify-end gap-3 animate-in fade-in slide-in-from-bottom-2 duration-300 delay-100">
                          <div className="chat_bubble_container user">
                            <div className="imessage-bubble imessage-from-me">
                              {customUserMessage}
                            </div>
                          </div>
                          <div className="min-w-10">
                            <UserAvatar />
                          </div>
                        </div>

                        {/* GAIA Image outside bubble */}
                        <div className="mb-3 ml-10.75 animate-in fade-in slide-in-from-bottom-2 duration-300 delay-200">
                          <OgImage />
                        </div>

                        {/* Bot message and buttons */}
                        <div className="flex items-start gap-1">
                          {/* GAIA logo */}
                          <div className="min-w-10 shrink-0 animate-in fade-in zoom-in-95 duration-300 delay-300">
                            <GaiaLogo />
                          </div>

                          <div className="flex-1 flex flex-col gap-3">
                            {/* Bot message bubble */}
                            <div className="chat_bubble_container animate-in fade-in slide-in-from-bottom-2 duration-300 delay-400">
                              <div className="imessage-bubble imessage-from-them text-white">
                                Hey! Sign up to start chatting with me 👋
                              </div>
                            </div>

                            {/* Buttons below bubble */}
                            <div className="flex gap-2 animate-in fade-in slide-in-from-bottom-2 duration-300 delay-500">
                              <Link href="/signup">
                                <RaisedButton
                                  color={"#00bbff"}
                                  className="text-black!"
                                >
                                  Get Started
                                  <ChevronRight width={16} height={16} />
                                </RaisedButton>
                              </Link>
                              <Link href="/login">
                                <RaisedButton
                                  className="border-0 outline-none"
                                  color={"#3f3f46"}
                                >
                                  Login
                                  <Login02Icon width={16} height={16} />
                                </RaisedButton>
                              </Link>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* User bubble */}
                    {showUser && (
                      <div
                        key={`user-${uc.id}`}
                        className="mb-2 flex w-full items-end justify-end gap-3 animate-in fade-in slide-in-from-bottom-2 duration-200"
                      >
                        <div
                          className="chat_bubble_container user group"
                          id={`user-${uc.id}`}
                        >
                          <div className="imessage-bubble imessage-from-me">
                            {uc.userMessage}
                          </div>
                          <div className="invisible pointer-events-none flex flex-col items-end justify-end gap-1 pb-3 opacity-0 transition-all group-hover:visible group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:visible group-focus-within:pointer-events-auto group-focus-within:opacity-100">
                            <span className="flex flex-col text-xs text-zinc-400 select-text">
                              just now
                            </span>
                            <div className="flex w-fit items-center">
                              {[
                                { Icon: LinkBackwardIcon, label: "Reply" },
                                { Icon: Copy01Icon, label: "Copy" },
                                { Icon: PinIcon, label: "Pin" },
                              ].map(({ Icon, label }) => (
                                <button
                                  key={label}
                                  type="button"
                                  aria-label={label}
                                  title={label}
                                  className="aspect-square size-7.5 min-w-7.5 rounded-md p-0 text-zinc-500 hover:text-zinc-300"
                                >
                                  <Icon height="18" width="18" />
                                </button>
                              ))}
                            </div>
                          </div>
                        </div>
                        <div className="min-w-10">
                          <AryanAvatar />
                        </div>
                      </div>
                    )}

                    {/* Loading indicator */}
                    <AnimatePresence mode="wait">
                      {showLoading && (
                        <m.div
                          key={`loading-${uc.id}-${loadingKey}`}
                          initial={{ opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -6 }}
                          transition={tx}
                          className="mb-4 flex items-center gap-3"
                        >
                          {toolIcon ?? <MiniWaveSpinner />}
                          <AnimatePresence mode="wait">
                            <m.span
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
                            </m.span>
                          </AnimatePresence>
                        </m.div>
                      )}
                    </AnimatePresence>

                    {/* Bot row: tool calls → text → final card */}
                    <div
                      id={`bot-${uc.id}`}
                      className="group relative flex flex-col"
                    >
                      {/* Tool calls — above all bot content */}
                      {showTools && (
                        <div className="mb-2 ml-10.75">
                          <MemoDemoToolCalls
                            tools={uc.tools}
                            expanded={toolsExpanded}
                            onToggle={handleToolsToggle}
                          />
                        </div>
                      )}

                      {/* Final card — above the text bubble, below tool calls */}
                      {showFinalCard && (
                        <div
                          key={`card-${uc.id}`}
                          className="ml-10.75 mb-3 animate-in fade-in slide-in-from-bottom-2 zoom-in-95 duration-300"
                        >
                          <MemoDemoFinalCard type={uc.finalCard} />
                        </div>
                      )}

                      {/* Bot row: logo + text bubble — always at the bottom */}
                      <div className="flex items-end gap-1">
                        {/* GAIA logo — pinned to bottom, only with response */}
                        <div className="relative bottom-0 min-w-10 shrink-0">
                          {showBotLogo && (
                            <div
                              key="bot-logo"
                              className="animate-in fade-in zoom-in-95 duration-200"
                            >
                              <GaiaLogo className="relative z-10" />
                            </div>
                          )}
                        </div>

                        <div className="chatbubblebot_parent flex-1">
                          {/* Text response */}
                          {showResponse && (
                            <div
                              key={`response-${uc.id}`}
                              className="chat_bubble_container animate-in fade-in slide-in-from-bottom-1 duration-200"
                            >
                              <div className="imessage-bubble imessage-from-them text-white">
                                <TypingText
                                  ref={typingTextRef}
                                  text={uc.botResponse}
                                  isTyping={phase === "responding"}
                                />
                              </div>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Bot hover actions — always last, after all content */}
                      {showResponse && (
                        <div className="bot-actions ml-10.75 invisible flex flex-col opacity-0 transition-all duration-200 group-hover:visible group-hover:opacity-100">
                          <span className="p-1 py-2 text-xs text-nowrap text-zinc-400 select-text">
                            just now
                          </span>
                          <div className="flex w-fit items-center">
                            {[
                              { Icon: LinkBackwardIcon, label: "Reply" },
                              { Icon: Copy01Icon, label: "Copy" },
                              { Icon: PinIcon, label: "Pin" },
                              { Icon: ThumbsUpIcon, label: "Helpful" },
                              { Icon: ThumbsDownIcon, label: "Not helpful" },
                            ].map(({ Icon, label }) => (
                              <button
                                key={label}
                                type="button"
                                aria-label={label}
                                title={label}
                                className="aspect-square size-7.5 min-w-7.5 rounded-md p-0 text-zinc-500 hover:text-zinc-300"
                              >
                                <Icon height="18" width="18" />
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                {/* Composer */}
                <div className="relative shrink-0 px-4 pb-4 w-full">
                  <DummyComposer
                    hideIntegrationBanner
                    onSend={handleUserSend}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Use case chips + retry — only for chat demo */}
      {activePage === "chats" && (
        <div
          className={`relative mt-6 flex w-full flex-wrap items-center justify-end sm:justify-between gap-2 max-w-7xl ${isInView ? "animate-in fade-in slide-in-from-bottom-3 duration-[400ms] delay-200" : "opacity-0"}`}
        >
          <div className="hidden sm:block" />
          <div className="flex items-center justify-center gap-2">
            {USE_CASES.map((useCase, i) => (
              <Chip
                key={useCase.id}
                size="lg"
                variant={activeUseCase === i ? "shadow" : "flat"}
                className="cursor-pointer select-none"
                onClick={() => switchUseCase(i)}
              >
                {useCase.label}
              </Chip>
            ))}
          </div>

          <Button
            type="button"
            aria-label="Retry"
            title="Replay demo"
            onPress={handleRetry}
            isIconOnly
            radius="full"
            variant="flat"
          >
            <RedoIcon width={20} height={20} />
          </Button>
        </div>
      )}
    </div>
  );
}
