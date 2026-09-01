"use client";

import { useEffect, useRef, useState } from "react";

/** Where the agent is acting, as viewport fractions in [0,1], plus what it's doing. */
export interface AgentCursorTarget {
  x: number;
  y: number;
  kind: "click" | "type" | "move";
  label?: string;
  /** Changes per action so the ripple/animation re-fires even on the same point. */
  key: number;
}

// A Figma-style presence cursor overlaid on the live canvas: the pointer glides
// to each action's point, a ring ripples on a click, and a tag names what it's
// doing. The headless browser renders no cursor of its own, so this is the only
// thing that says "it's acting here" — it must read as alive, not decorative.
export function AgentCursor({ target }: { target: AgentCursorTarget | null }) {
  const [rippleKey, setRippleKey] = useState<number | null>(null);
  const lastKey = useRef<number | null>(null);

  useEffect(() => {
    if (!target || target.key === lastKey.current) return;
    lastKey.current = target.key;
    if (target.kind === "click") setRippleKey(target.key);
  }, [target]);

  if (!target) return null;
  const left = `${Math.min(100, Math.max(0, target.x * 100))}%`;
  const top = `${Math.min(100, Math.max(0, target.y * 100))}%`;

  return (
    <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden">
      <div
        className="absolute transition-[left,top] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] will-change-[left,top]"
        style={{ left, top }}
      >
        {/* Click ripple — remounted per action key so it replays each time. */}
        {rippleKey !== null && (
          <span
            key={rippleKey}
            className="absolute -left-4 -top-4 size-8 animate-ping rounded-full bg-[#00bbff]/40"
            onAnimationEnd={() => setRippleKey(null)}
          />
        )}
        <CursorArrow />
        {/* Name/action tag, Figma-style, offset from the pointer tip. */}
        {target.label && (
          <span className="absolute left-4 top-4 whitespace-nowrap rounded-md bg-[#00bbff] px-1.5 py-0.5 text-[11px] font-medium text-white shadow-sm">
            {target.kind === "type" ? (
              <span className="inline-flex items-center gap-1">
                {target.label}
                <span className="inline-flex gap-0.5">
                  <Dot delay="0ms" />
                  <Dot delay="150ms" />
                  <Dot delay="300ms" />
                </span>
              </span>
            ) : (
              target.label
            )}
          </span>
        )}
      </div>
    </div>
  );
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="inline-block size-1 animate-bounce rounded-full bg-white/90"
      style={{ animationDelay: delay }}
    />
  );
}

/** The agent's pointer — a Figma-style arrow in the browser accent. Shared by
 * the live overlay and the recap so both read as the same cursor, not a dot. */
export function CursorArrow({ className = "" }: { className?: string }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 16 16"
      fill="none"
      className={`drop-shadow-[0_1px_3px_rgba(0,0,0,0.5)] ${className}`}
      role="img"
      aria-label="Agent cursor"
    >
      <title>Agent cursor</title>
      <path
        d="M1 1L6.5 15L8.6 9.1L14.5 7L1 1Z"
        fill="#00bbff"
        stroke="white"
        strokeWidth="1.1"
        strokeLinejoin="round"
      />
    </svg>
  );
}
