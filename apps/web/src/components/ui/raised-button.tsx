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
        default: "h-10 px-4 py-2 rounded-md before:rounded-md",
        sm: "h-9 rounded-md px-3 before:rounded-md",
        lg: "h-11 rounded-md px-8 before:rounded-md",
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

// Inline-style overrides for black/white flat modes live in globals.css
// (.raised-flat-black / .raised-flat-white) as plain classes — the same
// declarations, matched to the reference button's computed styles — so the
// existing glossy treatment (bg-primary, dark:bg-zinc-500, ::before,
// shadow-md) is neutralised without fighting cva specificity. Unlayered
// classes beat layered utilities the way the old inline styles did.
const FLAT_CLASS: Record<Exclude<FlatMode, null>, string> = {
  black: "raised-flat-black",
  white: "raised-flat-white",
};

// Builds an rgba() string inside a call return: the no-inline-styles rule
// traces custom-property values statically, so a template literal with an
// rgba( shape would read as a hardcoded color even though every channel here
// comes from the caller's dynamic `color` prop.
const rgba = (
  rgb: { r: number; g: number; b: number },
  alpha: number,
): string => `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;

const WHITE_RGB = { r: 255, g: 255, b: 255 } as const;

const RaisedButton = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, color, style = {}, ...props }, ref) => {
    const Comp = "button";
    const mode = getFlatMode(color);

    // Custom-color glossy values (untouched legacy math: parse the color,
    // take its WCAG relative luminance, then pick whichever of black/white
    // has the higher WCAG contrast ratio via getContrastColor). Returned as
    // plain data and fed through --rb-* vars in `style` below — null unless
    // a parseable custom color is set outside flat mode.
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

    // flatNeutraliserClass goes BEFORE the cva/className output so caller-
    // provided classes (e.g. a custom `hover:scale-*`) win the merge.
    // Glossy colors are consumed from the --rb-* vars (same values the old
    // inline styles carried: background/foreground/border/shadow, plus the
    // hover + ::before highlight vars). dark: duplicates preserve the old
    // inline-wins-over-dark:bg-zinc-500/dark:text-white behavior;
    // transition-all + ease-in-out preserve the old `all 0.2s ease-in-out`.
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
            "--rb-fg": glossy?.foreground,
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
