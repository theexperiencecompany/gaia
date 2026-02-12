"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { AnimatePresence, m, useInView } from "motion/react";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { appConfig } from "@/config";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import DummyComposer from "@/features/landing/components/demo/DummyComposer";
import {
  Copy01Icon,
  LinkBackwardIcon,
  PinIcon,
  RedoIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "@/icons";
import DemoChatHeader from "./DemoChatHeader";
import { DemoFinalCard } from "./DemoFinalCards";
import DemoNotificationsPopover from "./DemoNotificationsPopover";
import DemoSidebar from "./DemoSidebar";
import DemoToolCalls from "./DemoToolCalls";
import { BASE_TIMINGS, ease, slideUp, tx, USE_CASES } from "./demoConstants";
import MiniWaveSpinner from "./MiniWaveSpinner";
import type { Phase } from "./types";

export default function ChatDemoSection() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [activeUseCase, setActiveUseCase] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [loadingText, setLoadingText] = useState("GAIA is thinking...");
  const [loadingKey, setLoadingKey] = useState(0);
  const [loadingCat, setLoadingCat] = useState<string | undefined>();
  const [toolsExpanded, setToolsExpanded] = useState(false);
  const [typedResponse, setTypedResponse] = useState("");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const messagesRef = useRef<HTMLDivElement>(null);
  const activeCaseRef = useRef(0);
  const hasStarted = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const isInView = useInView(containerRef, { once: true, amount: 0.2 });

  const clearAll = () => {
    for (const t of timers.current) clearTimeout(t);
    timers.current = [];
  };

  const add = (fn: () => void, delay: number) => {
    timers.current.push(setTimeout(fn, delay));
  };

  const scrollToBottom = () => {
    requestAnimationFrame(() => {
      if (messagesRef.current)
        messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    });
  };

  const runAnimation = (ucIndex: number) => {
    const useCase = USE_CASES[ucIndex];
    const T = BASE_TIMINGS;

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
        setTypedResponse(response.slice(0, i));
        if (i >= response.length) {
          clearInterval(tick);
          setTypedResponse(response);
        }
      }, 18);
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
  };

  useEffect(() => {
    if (isInView && !hasStarted.current) {
      hasStarted.current = true;
      runAnimation(0);
    }
    return () => clearAll();
  }, [isInView]);

  const switchUseCase = (idx: number) => {
    activeCaseRef.current = idx;
    setActiveUseCase(idx);
    runAnimation(idx);
  };

  const uc = USE_CASES[activeUseCase];

  const showUser = phase !== "idle";
  const showLoading = ["thinking", "loading1", "loading2"].includes(phase);
  const showTools = ["tool_calls", "responding", "final_card", "done"].includes(
    phase,
  );
  const showResponse = ["responding", "final_card", "done"].includes(phase);
  const showFinalCard = ["final_card", "done"].includes(phase);
  const showBotLogo = showTools || showResponse;

  return (
    <div
      ref={containerRef}
      className="relative flex w-full flex-col items-center"
    >
      <m.div
        initial={{ opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.4 }}
        className="mb-8 text-center"
      >
        <p className="mb-2 text-sm uppercase tracking-widest text-primary">
          See it in action
        </p>
        <h2 className="text-3xl font-semibold tracking-tight text-white">
          Your GAIA, actually working
        </h2>
      </m.div>

      {/* Demo window */}
      <m.div
        initial={{ opacity: 0, y: 24, scale: 0.97 }}
        whileInView={{ opacity: 1, y: 0, scale: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, ease }}
        className="overflow-hidden rounded-3xl h-[85vh] w-[80vw]"
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
          <DemoSidebar open={sidebarOpen} />

          <div
            className="relative flex min-w-0 flex-1 flex-col"
            style={{ backgroundColor: "#111111" }}
          >
            <DemoChatHeader
              sidebarOpen={sidebarOpen}
              onToggleSidebar={() => setSidebarOpen((o) => !o)}
              onNotificationsClick={() => setNotificationsOpen((o) => !o)}
            />

            <DemoNotificationsPopover
              open={notificationsOpen}
              onClose={() => setNotificationsOpen(false)}
            />

            {/* Messages — slightly narrower than full for visual breathing room */}
            <div ref={messagesRef} className="flex-1 overflow-y-auto px-4 py-3">
              <div className="mx-auto w-full max-w-2xl">
                {/* User bubble */}
                <AnimatePresence>
                  {showUser && (
                    <m.div
                      key={`user-${uc.id}`}
                      variants={slideUp}
                      initial="initial"
                      animate="animate"
                      exit="exit"
                      transition={tx}
                      className="mb-2 flex w-full items-end justify-end gap-3"
                    >
                      <div
                        className="chat_bubble_container user group"
                        id={`user-${uc.id}`}
                      >
                        <div className="imessage-bubble imessage-from-me">
                          {uc.userMessage}
                        </div>
                        <div className="flex flex-col items-end justify-end gap-1 pb-3 opacity-0 transition-all group-hover:opacity-100">
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
                        <Avatar className="relative bottom-18 rounded-full border border-white/10 bg-black">
                          <AvatarImage
                            src="https://github.com/aryanranderiya.png"
                            alt="Aryan"
                          />
                          <AvatarFallback className="bg-primary/20 text-xs font-medium text-primary">
                            AR
                          </AvatarFallback>
                        </Avatar>
                      </div>
                    </m.div>
                  )}
                </AnimatePresence>

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
                  onMouseOver={(e) => {
                    const el =
                      e.currentTarget.querySelector<HTMLElement>(
                        ".bot-actions",
                      );
                    if (el) {
                      el.style.opacity = "1";
                      el.style.visibility = "visible";
                    }
                  }}
                  onMouseOut={(e) => {
                    const el =
                      e.currentTarget.querySelector<HTMLElement>(
                        ".bot-actions",
                      );
                    if (el) {
                      el.style.opacity = "0";
                      el.style.visibility = "hidden";
                    }
                  }}
                >
                  {/* Tool calls — above all bot content */}
                  <AnimatePresence>
                    {showTools && (
                      <div className="mb-2 ml-10.75">
                        <DemoToolCalls
                          tools={uc.tools}
                          expanded={toolsExpanded}
                          onToggle={() => setToolsExpanded((e) => !e)}
                        />
                      </div>
                    )}
                  </AnimatePresence>

                  {/* Final card — above the text bubble, below tool calls */}
                  <AnimatePresence>
                    {showFinalCard && (
                      <m.div
                        key={`card-${uc.id}`}
                        initial={{ opacity: 0, y: 10, scale: 0.97 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        transition={{
                          duration: 0.3,
                          ease: [0.34, 1.2, 0.64, 1],
                        }}
                        className="ml-10.75 mb-3"
                      >
                        <DemoFinalCard type={uc.finalCard} />
                      </m.div>
                    )}
                  </AnimatePresence>

                  {/* Bot row: logo + text bubble — always at the bottom */}
                  <div className="flex items-end gap-1">
                    {/* GAIA logo — pinned to bottom, only with response */}
                    <div className="relative bottom-0 min-w-10 shrink-0">
                      <AnimatePresence>
                        {showBotLogo && (
                          <m.div
                            key="bot-logo"
                            initial={{ opacity: 0, scale: 0.8 }}
                            animate={{ opacity: 1, scale: 1 }}
                            transition={tx}
                          >
                            <Image
                              src="/images/logos/logo.webp"
                              width={28}
                              height={28}
                              loading="lazy"
                              alt="GAIA"
                              className="relative z-10"
                            />
                          </m.div>
                        )}
                      </AnimatePresence>
                    </div>

                    <div className="chatbubblebot_parent flex-1">
                      {/* Text response */}
                      <AnimatePresence>
                        {showResponse && (
                          <m.div
                            key={`response-${uc.id}`}
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={tx}
                            className="chat_bubble_container"
                          >
                            <div className="imessage-bubble imessage-from-them text-white">
                              {typedResponse}
                              {phase === "responding" && (
                                <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse bg-white/60 align-middle" />
                              )}
                            </div>
                          </m.div>
                        )}
                      </AnimatePresence>
                    </div>
                  </div>

                  {/* Bot hover actions — always last, after all content */}
                  {showResponse && (
                    <div
                      className="bot-actions ml-10.75 flex flex-col transition-all"
                      style={{ opacity: 0, visibility: "hidden" }}
                    >
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
            <div className="relative shrink-0 px-4 pb-4 [&_.searchbar]:w-[65%]! [&_.searchbar_container]:w-full!">
              <DummyComposer hideIntegrationBanner />
            </div>
          </div>
        </div>
      </m.div>

      {/* Use case chips + retry */}
      <m.div
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.4, delay: 0.2 }}
        className="relative mt-6 flex w-full flex-wrap items-center justify-between gap-2 max-w-7xl"
      >
        <div />
        <div className="flex items-center justify-center gap-2">
          {USE_CASES.map((useCase, i) => (
            <Chip
              key={useCase.id}
              // radius="sm"
              size="lg"
              variant={activeUseCase === i ? "shadow" : "flat"}
              className={`cursor-pointer select-none`}
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
          onPress={() => switchUseCase(activeUseCase)}
          isIconOnly
          radius="full"
          variant="flat"
        >
          <RedoIcon width={20} height={20} />
        </Button>
      </m.div>
    </div>
  );
}
