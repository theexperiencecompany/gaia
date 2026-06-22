"use client";

import type { CSSProperties } from "react";
import { cn } from "@/lib/utils";

interface ShineBorderProps {
  /** Width of the border in pixels. */
  borderWidth?: number;
  /** Duration of one full sweep, in seconds. */
  duration?: number;
  /** Color(s) of the animated shine. */
  shineColor?: string | string[];
  className?: string;
  style?: CSSProperties;
}

/**
 * Animated gradient border (magicui ShineBorder). Renders an absolutely
 * positioned masked overlay that sweeps a gradient around the parent's border.
 * The parent must be `relative` and rounded; this inherits its radius.
 * https://magicui.design/docs/components/shine-border
 */
export function ShineBorder({
  borderWidth = 1,
  duration = 14,
  shineColor = "#000000",
  className,
  style,
}: ShineBorderProps) {
  return (
    <div
      style={
        {
          "--border-width": `${borderWidth}px`,
          "--duration": `${duration}s`,
          backgroundImage: `radial-gradient(transparent,transparent, ${
            Array.isArray(shineColor) ? shineColor.join(",") : shineColor
          },transparent,transparent)`,
          backgroundSize: "300% 300%",
          mask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
          WebkitMask:
            "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
          WebkitMaskComposite: "xor",
          maskComposite: "exclude",
          padding: "var(--border-width)",
          ...style,
        } as CSSProperties
      }
      className={cn(
        "pointer-events-none absolute inset-0 size-full rounded-[inherit] will-change-[background-position] motion-safe:animate-shine-border",
        className,
      )}
    />
  );
}
