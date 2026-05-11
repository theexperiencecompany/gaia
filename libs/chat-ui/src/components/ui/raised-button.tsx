"use client";

import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";
import { getContrastColor, getLuminance, parseColor } from "@/utils/colorUtils";

const raisedButtonVariants = cva(
  "inline-flex items-center justify-center dark:bg-zinc-500 dark:text-white whitespace-nowrap  text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 relative bg-primary text-primary-foreground hover:bg-primary/90 border border-primary/50 shadow-md before:absolute before:inset-0 before:border-t before:border-white/40 before:bg-gradient-to-b before:from-white/20 before:to-transparent cursor-pointer transition-transform duration-200 active:scale-[0.96] subpixel-antialiased gap-2",
  {
    variants: {
      variant: {
        default: "",
        // Keep existing variants and add more if needed
      },
      size: {
        default: "h-10 px-4 py-2 rounded-xl before:rounded-xl",
        sm: "h-9 rounded-lg px-3 before:rounded-xl",
        lg: "h-11 rounded-lg px-8 before:rounded-lg",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof raisedButtonVariants> {
  color?: string; // Add color prop for custom colors
}

// Detect if a color is essentially black or white so we can swap to a flat
// treatment for those two cases only. Every other color keeps the existing
// glossy raised look untouched.
type FlatMode = "black" | "white" | null;

const getFlatMode = (color: string | undefined): FlatMode => {
  if (!color) return null;
  const rgb = parseColor(color);
  if (!rgb) return null;
  const { r, g, b } = rgb;
  if (r < 24 && g < 24 && b < 24) return "black";
  if (r > 232 && g > 232 && b > 232) return "white";
  return null;
};

// Inline-style overrides for black + white flat modes. Inline styles are used
// instead of Tailwind classes so the existing glossy treatment (bg-primary,
// dark:bg-zinc-500, ::before overlay, shadow-md) can be neutralised in one
// place without fighting cva specificity or class-detection edge cases.
const FLAT_BLACK_STYLE: React.CSSProperties = {
  background: "linear-gradient(to bottom, #444, #000)",
  borderColor: "#111113",
  color: "#ffffff",
  boxShadow: "none",
};

const FLAT_WHITE_STYLE: React.CSSProperties = {
  background: "#ffffff",
  borderColor: "rgba(0, 0, 0, 0.18)",
  color: "#18181b",
  boxShadow: "0 1px 2px rgba(0, 0, 0, 0.08), 0 0 0 1px rgba(0, 0, 0, 0.08)",
};

const RaisedButton = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, color, style = {}, ...props }, ref) => {
    const Comp = "button";
    const mode = getFlatMode(color);

    // Custom-color glossy treatment (untouched legacy path).
    const dynamicStyles = React.useMemo(() => {
      if (!color || mode) return {};

      try {
        const rgb = parseColor(color);
        if (!rgb) return {};

        const luminance = getLuminance(rgb);
        const textColor = getContrastColor(luminance);
        const borderOpacity = 0.5;
        const hoverOpacity = 0.9;
        const whiteBorderOpacity = 0.6;
        const whiteGradientOpacity = 0.3;
        const shadowOpacity = 0.2;
        const shadowSpread = "0px";
        const shadowBlur = "5px";

        return {
          backgroundColor: color,
          color: textColor,
          borderColor: `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${borderOpacity})`,
          "--hover-bg": `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${hoverOpacity})`,
          "--border": `rgba(255, 255, 255, ${whiteBorderOpacity})`,
          "--gradient": `rgba(255, 255, 255, ${whiteGradientOpacity})`,
          "--shadow-color": `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${shadowOpacity})`,
          boxShadow: `0 4px ${shadowBlur} ${shadowSpread} var(--shadow-color)`,
          transition: "all 0.2s ease-in-out",
        };
      } catch (e) {
        console.error("Error processing color:", e);
        return {};
      }
    }, [color, mode]);

    // For flat modes, hide the ::before glossy overlay and remove the dark
    // theme bg/text override that ships in the cva base, while keeping size
    // utilities + caller overrides.
    const flatNeutraliserClass = mode
      ? "before:hidden hover:scale-[0.98] hover:bg-transparent dark:bg-transparent dark:text-inherit"
      : "";

    const flatStyle: React.CSSProperties = mode
      ? mode === "black"
        ? FLAT_BLACK_STYLE
        : FLAT_WHITE_STYLE
      : {};

    // flatNeutraliserClass goes BEFORE the cva/className output so caller-
    // provided classes (e.g. a custom `hover:scale-*`) win the merge.
    const computedClassName = cn(
      flatNeutraliserClass,
      raisedButtonVariants({ variant, size, className }),
      !mode &&
        color &&
        "hover:bg-[color:var(--hover-bg)] before:border-[color:var(--border)] before:from-[color:var(--gradient)] hover:opacity-80 overflow-hidden",
    );

    return (
      <Comp
        className={computedClassName}
        ref={ref}
        style={{
          ...style,
          ...dynamicStyles,
          ...flatStyle,
        }}
        {...props}
      />
    );
  },
);
RaisedButton.displayName = "RaisedButton";

export { RaisedButton, raisedButtonVariants };
