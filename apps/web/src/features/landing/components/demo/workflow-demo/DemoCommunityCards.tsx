"use client";

import { Button } from "@heroui/button";
import { AnimatePresence, m } from "motion/react";
import Image from "next/image";
import { useEffect, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { PlayIcon, ZapIcon } from "@/icons";
import {
  COMMUNITY_WORKFLOWS,
  type WorkflowDemoPhase,
  wfEase,
} from "./workflowDemoConstants";

interface DemoCommunityCardsProps {
  phase: WorkflowDemoPhase;
  colorScheme?: "dark" | "light";
}

export default function DemoCommunityCards({
  phase,
  colorScheme = "dark",
}: DemoCommunityCardsProps) {
  const light = colorScheme === "light";
  const [rippleActive, setRippleActive] = useState(false);

  const showButtonOnly = phase === "publish_button";
  const showClickState = phase === "publish_click";
  const showButton = showButtonOnly || showClickState;
  const showCards = ["community_cards", "done"].includes(phase);

  useEffect(() => {
    if (phase === "publish_click") {
      setRippleActive(true);
      const t = setTimeout(() => setRippleActive(false), 600);
      return () => clearTimeout(t);
    }
  }, [phase]);

  useEffect(() => {
    if (phase === "idle") {
      setRippleActive(false);
    }
  }, [phase]);

  return (
    <div className="flex w-full flex-col items-center justify-center min-h-[200px]">
      <AnimatePresence>
        {showButton && (
          <m.div
            key="publish-btn"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95, y: -10 }}
            transition={{ duration: 0.3, ease: wfEase }}
            style={{ willChange: "transform, opacity" }}
          >
            <div className="relative">
              <RaisedButton
                color="#000000"
                size={"lg"}
                className="rounded-2xl text-xl! px-6! py-5!"
              >
                Publish Workflow
              </RaisedButton>
              <AnimatePresence>
                {rippleActive && (
                  <m.div
                    key="ripple"
                    initial={{ scale: 0.3, opacity: 0.6 }}
                    animate={{ scale: 2, opacity: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.6, ease: "easeOut" }}
                    className="pointer-events-none absolute inset-0 rounded-xl bg-black/30"
                  />
                )}
              </AnimatePresence>
            </div>
          </m.div>
        )}

        {showCards && (
          <m.div
            key="community-section"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3, ease: wfEase }}
            className="w-full"
          >
            <m.p
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, ease: wfEase }}
              className={`mb-4 text-center font-medium ${light ? "text-zinc-600" : "text-zinc-800"}`}
            >
              Community Workflows
            </m.p>

            <div className="grid grid-cols-3 gap-2">
              {COMMUNITY_WORKFLOWS.map((wf, i) => (
                <m.div
                  key={wf.title}
                  initial={{ opacity: 0, y: 20, scale: 0.9 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  transition={{
                    delay: i * 0.15,
                    type: "spring",
                    stiffness: 350,
                    damping: 25,
                  }}
                  style={{ willChange: "transform, opacity" }}
                  className={`flex flex-col gap-2 rounded-3xl p-4 outline ${
                    light
                      ? "bg-white/70 backdrop-blur-lg outline-zinc-200/60"
                      : "bg-zinc-800 outline-zinc-700/40"
                  }`}
                >
                  {/* Icon stack - matches WorkflowIcons component */}
                  <div className="flex min-h-8 items-center -space-x-1.5">
                    {wf.categories.slice(0, 3).map((cat, j) => (
                      <div
                        key={cat}
                        className="relative flex min-w-8 items-center justify-center"
                        style={{
                          rotate:
                            wf.categories.length > 1
                              ? j % 2 === 0
                                ? "8deg"
                                : "-8deg"
                              : "0deg",
                          zIndex: j,
                        }}
                      >
                        {getToolCategoryIcon(cat, {
                          width: 25,
                          height: 25,
                        })}
                      </div>
                    ))}
                  </div>

                  {/* Title + description */}
                  <div>
                    <h5
                      className={`line-clamp-2 text-lg font-medium ${light ? "text-zinc-800" : "text-zinc-200"}`}
                    >
                      {wf.title}
                    </h5>
                    <p
                      className={`mt-1 line-clamp-2 min-h-8 text-xs ${light ? "text-zinc-600" : "text-zinc-500"}`}
                    >
                      {wf.description}
                    </p>
                  </div>

                  {/* Footer - matches UnifiedWorkflowCard */}
                  <div className="mt-auto flex items-center justify-between gap-2">
                    <div
                      className={`flex items-center gap-1 text-xs ${light ? "text-zinc-600" : "text-zinc-500"}`}
                    >
                      <PlayIcon
                        width={15}
                        height={15}
                        className={`w-4 ${light ? "text-zinc-600" : "text-zinc-500"}`}
                      />
                      <span className="text-nowrap">{wf.executions} runs</span>
                    </div>

                    <div className="flex items-center gap-3">
                      {/* Creator avatar */}
                      <div className="flex h-7 w-7 items-center justify-center rounded-full">
                        <Image
                          src={wf.creator.avatar}
                          alt={wf.creator.name}
                          width={27}
                          height={27}
                          loading="lazy"
                          className="h-7 w-7 rounded-full"
                        />
                      </div>

                      {/* Action button */}
                      <Button
                        color="primary"
                        size="sm"
                        className="rounded-xl font-medium"
                        endContent={<ZapIcon width={16} height={16} />}
                      >
                        Create
                      </Button>
                    </div>
                  </div>
                </m.div>
              ))}
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}
