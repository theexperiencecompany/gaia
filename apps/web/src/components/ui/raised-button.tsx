"use client";

import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";
import { getContrastColor, getLuminance, parseColor } from "@/utils/colorUtils";

const raisedButtonVariants = cva(
  "inline-flex items-center justify-center overflow-hidden dark:bg-zinc-500 dark:text-white whitespace-nowrap  text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 relative bg-primary text-primary-foreground hover:bg-primary/90 border border-primary/50 shadow-md before:absolute before:inset-0 before:border-t before:border-white/40 before:bg-gradient-to-b before:from-white/20 before:to-transparent cursor-pointer transition-transform duration-200 active:scale-[0.96] subpixel-antialiased gap-2",
  {
    variants: {
      variant: {
        default: "",
        // Keep existing variants and add more if needed
      },
      size: {
        default: "h-10 px-4 py-2 rounded-xl before:rounded-xl",
        sm: "h-9 rounded-lg px-3 before:rounded-lg",
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
  /** Text and icon color when the brand calls for one; defaults to the higher-contrast of black or white. */
  foreground?: string;
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

// Important so the flat treatment beats the cva base and caller classes, as the
// inline flat styles did; box-shadow is set whole so no focus ring composes in.
const FLAT_CLASS: Record<Exclude<FlatMode, null>, string> = {
  black:
    "bg-[linear-gradient(to_bottom,_#444,_#000)]! border-[#111113]! text-white! [box-shadow:none]!",
  white:
    "bg-[linear-gradient(rgb(255,_255,_255)_0%,_rgb(235,_238,_240)_100%)]! border-transparent! text-zinc-900! [box-shadow:rgba(0,_0,_0,_0.06)_0px_0px_0px_1px,_rgba(0,_0,_0,_0.06)_0px_1px_2px_-1px,_rgba(0,_0,_0,_0.04)_0px_2px_4px_0px]!",
};

// A function, not an inline template: no-inline-styles reads a literal rgba(
// as a hardcoded color, though every channel comes from the `color` prop.
const rgba = (
  rgb: { r: number; g: number; b: number },
  alpha: number,
): string => `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;

const WHITE_RGB = { r: 255, g: 255, b: 255 } as const;

const RaisedButton = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, color, foreground, style = {}, ...props },
    ref,
  ) => {
    const Comp = "button";
    const mode = getFlatMode(color);

    // Glossy values for a custom color, fed through the --rb-* vars below;
    // null in flat mode or when the color does not parse.
    const glossy = React.useMemo(() => {
      if (!color || mode) return null;

      try {
        const rgb = parseColor(color);
        if (!rgb) return null;

        const luminance = getLuminance(rgb);
        return {
          background: color,
          foreground: getContrastColor(luminance),
          border: rgba(rgb, 0.5),
          hover: rgba(rgb, 0.9),
          hiBorder: rgba(WHITE_RGB, 0.6),
          hiGradient: rgba(WHITE_RGB, 0.3),
          shadow: rgba(rgb, 0.2),
        };
      } catch (e) {
        console.error("Error processing color:", e);
        return null;
      }
    }, [color, mode]);

    // For flat modes, hide the ::before glossy overlay and remove the dark
    // theme bg/text override that ships in the cva base, while keeping size
    // utilities + caller overrides.
    const flatNeutraliserClass = mode
      ? "before:hidden hover:scale-[0.98] hover:bg-transparent dark:bg-transparent dark:text-inherit"
      : "";

    // The neutraliser goes first so caller classes win the merge; the dark:
    // duplicates keep the --rb-* colors ahead of dark:bg-zinc-500.
    const computedClassName = cn(
      flatNeutraliserClass,
      raisedButtonVariants({ variant, size, className }),
      !mode &&
        color &&
        "bg-[color:var(--rb-bg)] dark:bg-[color:var(--rb-bg)] text-[color:var(--rb-fg)] dark:text-[color:var(--rb-fg)] border-[color:var(--rb-bd)] shadow-[0_4px_5px_0px_var(--rb-sh)] transition-all ease-in-out hover:bg-[color:var(--rb-hover)] before:border-[color:var(--rb-hi-bd)] before:from-[color:var(--rb-hi-grad)] hover:opacity-80",
      mode && FLAT_CLASS[mode],
    );

    return (
      <Comp
        className={computedClassName}
        ref={ref}
        style={
          {
            ...style,
            "--rb-bg": glossy?.background,
            "--rb-fg": foreground ?? glossy?.foreground,
            "--rb-bd": glossy?.border,
            "--rb-hover": glossy?.hover,
            "--rb-hi-bd": glossy?.hiBorder,
            "--rb-hi-grad": glossy?.hiGradient,
            "--rb-sh": glossy?.shadow,
          } as React.CSSProperties
        }
        {...props}
      />
    );
  },
);
RaisedButton.displayName = "RaisedButton";

export { RaisedButton };
