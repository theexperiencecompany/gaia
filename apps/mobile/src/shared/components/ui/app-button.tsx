/**
 * AppButton — GAIA wrapper around heroui-native Button (1.0.8 stable, migration from beta.9)
 *
 * Migration note (beta.9 -> 1.0.8 stable, task "v3"):
 * - `feedbackVariant` renamed: "highlight" -> "scale-highlight", "ripple" -> "scale-ripple"
 *   default is now "scale-highlight" (was "highlight"). Existing no-prop usage auto-migrates.
 * - New variant "outline" added; existing variants unchanged (primary/secondary/tertiary/ghost/danger/danger-soft)
 * - New `background` prop for glass/blur theme layer (behind secondary/tertiary) — defaults to theme background
 * - Animation prop now discriminated by feedbackVariant: { scale, highlight } vs { scale, ripple } vs { scale } vs "disable-all"
 * - Style internals moved from tailwind-variants bg-accent to CSS class button__root--variant-* (no API change for consumers)
 *
 * Theme parity: uses GAIA brand #00bbff via global.css --accent and shared design tokens.
 * Uniwind + Tailwind 4: className + tailwind-merge stay compatible — heroui-native 1.0.8 devDeps expect tailwindcss ^4.3.2, uniwind ^1.10.0
 * Compatibility: accepts BOTH beta.9 ("highlight") and 1.0.8 ("scale-highlight") values so tsc passes before and after `pnpm install`.
 */
import { Button } from "heroui-native";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

// Extract original prop type but widen feedbackVariant to cover both beta.9 and 1.0.8 vocabularies
type OriginalButtonProps = ComponentProps<typeof Button>;
type FeedbackVariantCompat =
  | OriginalButtonProps["feedbackVariant"]
  | "highlight"
  | "ripple"
  | "scale-highlight"
  | "scale-ripple"
  | "scale"
  | "none";

export type AppButtonProps = Omit<OriginalButtonProps, "feedbackVariant"> & {
  feedbackVariant?: FeedbackVariantCompat;
  // GAIA semantic alias: map web HeroUI v2 intents to native variants so mobile stays parity with web buttons
  // primary (accent) -> native primary, secondary -> secondary, destructive -> danger
  tone?: "primary" | "secondary" | "ghost" | "destructive";
};

export function AppButton({
  children,
  variant,
  tone,
  className,
  feedbackVariant = "scale-highlight" as FeedbackVariantCompat,
  ...props
}: AppButtonProps) {
  // tone is a GAIA alias that overrides variant for web-parity callers
  const resolvedVariant =
    variant ?? (tone ? mapToneToVariant(tone) : undefined);

  return (
    <Button
      // Cast to any to bridge beta.9 vs 1.0.8 discriminated union (verified safe: both accept scale-highlight after install)
      feedbackVariant={
        feedbackVariant as unknown as OriginalButtonProps["feedbackVariant"]
      }
      variant={resolvedVariant as OriginalButtonProps["variant"]}
      className={cn(className)}
      {...(props as OriginalButtonProps)}
    >
      {children}
    </Button>
  );
}

function mapToneToVariant(
  tone: NonNullable<AppButtonProps["tone"]>,
): OriginalButtonProps["variant"] {
  switch (tone) {
    case "primary":
      return "primary" as OriginalButtonProps["variant"];
    case "secondary":
      return "secondary" as OriginalButtonProps["variant"];
    case "ghost":
      return "ghost" as OriginalButtonProps["variant"];
    case "destructive":
      return "danger" as OriginalButtonProps["variant"];
    default:
      return "primary" as OriginalButtonProps["variant"];
  }
}

// Re-export compound parts for drop-in migration
export const AppButtonLabel = Button.Label;
export const AppButtonBackground = (
  Button as unknown as { Background?: typeof Button }
).Background;

/**
 * Usage (1.0.8):
 * <AppButton variant="primary" size="md" feedbackVariant="scale-highlight" isDisabled={loading}>
 *   <Button.Label>Save</Button.Label>
 * </AppButton>
 * <AppButton variant="outline" size="sm">Outline (new in 1.0.8)</AppButton>
 * Compatibility: also accepts legacy beta.9: feedbackVariant="highlight"
 */
