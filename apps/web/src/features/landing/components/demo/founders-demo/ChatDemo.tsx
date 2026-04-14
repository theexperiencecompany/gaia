import { useInView } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useRef, useState } from "react";
import DemoToolCalls from "../DemoToolCalls";
import MiniWaveSpinner from "../MiniWaveSpinner";
import { SimpleChatBubbleBot } from "../SimpleChatBubbles";
import type { ChatMessage } from "./types";

const ease = [0.22, 1, 0.36, 1] as const;

const CHAT_CONTAINER_STYLE = {
  "--color-primary-bg": "#18181b",
} as React.CSSProperties;

function LandingUserBubble({ content }: { content: string }) {
  return (
    <div className="mb-3 flex items-end justify-end gap-3">
      <div className="imessage-bubble imessage-from-me select-none text-sm">
        {content}
      </div>
      <div className="w-[35px] shrink-0" />
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div className="mb-3 flex items-end gap-3">
      <div className="relative z-[1] flex h-[35px] w-[35px] items-center justify-center">
        <MiniWaveSpinner />
      </div>
    </div>
  );
}

export default function ChatDemo({
  messages,
  minHeight = 220,
}: {
  messages: ChatMessage[];
  minHeight?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.25 });
  const [visibleCount, setVisibleCount] = useState(1);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (!inView) return;

    let cumDelay = 0;
    messages.slice(1).forEach((msg, i) => {
      const d = msg.delay ?? (msg.role === "tools" ? 250 : 500);
      cumDelay += d;
      timersRef.current.push(
        setTimeout(() => setVisibleCount(i + 2), cumDelay),
      );
    });

    const captured = timersRef.current;
    return () => {
      for (const t of captured) clearTimeout(t);
    };
  }, [inView, messages]);

  useEffect(() => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    });
  }, [visibleCount]);

  function toggleExpand(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div
      ref={ref}
      className="flex flex-col overflow-hidden rounded-3xl bg-zinc-900 p-5 text-left"
      style={{ ...CHAT_CONTAINER_STYLE, minHeight }}
    >
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 space-y-1 overflow-y-auto no-scrollbar"
      >
        {messages.slice(0, visibleCount).map((msg, i) => {
          if (msg.role === "thinking" && i < visibleCount - 1) return null;

          return (
            <m.div
              key={msg.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, ease }}
            >
              {msg.role === "user" && (
                <LandingUserBubble content={msg.content} />
              )}
              {msg.role === "thinking" && <ThinkingIndicator />}
              {msg.role === "tools" && msg.tools && (
                <div className="mb-2 pl-[47px]">
                  <DemoToolCalls
                    tools={msg.tools}
                    expanded={expandedIds.has(msg.id)}
                    onToggle={() => toggleExpand(msg.id)}
                  />
                </div>
              )}
              {msg.role === "assistant" && (
                <SimpleChatBubbleBot>{msg.content}</SimpleChatBubbleBot>
              )}
              {msg.role === "card" && (
                <div className="mb-3 pl-[47px]">{msg.cardContent}</div>
              )}
            </m.div>
          );
        })}
      </div>
    </div>
  );
}
