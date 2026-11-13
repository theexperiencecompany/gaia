import { cn } from "@/lib/utils";

/**
 * Fractal-noise tile rendered via an inlined SVG filter — no request, no
 * decode. `stitchTiles` keeps it seamless when repeated.
 *
 * A single octave at high base frequency reads as film grain; stacking
 * octaves sums to cloudy haze instead. `feColorMatrix` desaturates it since
 * raw feTurbulence writes independent R/G/B that would tint whatever it sits on.
 */
const GRAIN_TILE =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160' viewBox='0 0 160 160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='1' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)'/%3E%3C/svg%3E\")";

/**
 * How the grain composites — picking the wrong blend makes it invisible.
 *
 * `photo` (dark, detailed art): overlay degrades to multiply against dark
 * pixels and the grain vanishes into shadow, so composite normally at low
 * opacity instead. `surface` (smooth gradients/flat color): overlay is
 * right here — it ties speckle to the underlying hue at a lower opacity.
 */
const VARIANT_CLASSES = {
  photo: "opacity-[0.24]",
  surface: "opacity-[0.06] mix-blend-overlay",
} as const;

interface GrainOverlayProps {
  variant?: keyof typeof VARIANT_CLASSES;
  /** Match the parent's radius so the grain is clipped to the same shape. */
  className?: string;
}

/**
 * Film-grain layer for images and large gradient surfaces — breaks up banding
 * and gives flat artwork a tactile, printed feel. Absolutely positioned, so
 * the parent must be positioned and should clip (`overflow-hidden` or a
 * matching radius on this element).
 */
export function GrainOverlay({
  variant = "photo",
  className,
}: GrainOverlayProps) {
  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0",
        VARIANT_CLASSES[variant],
        className,
      )}
      style={{ backgroundImage: GRAIN_TILE }}
    />
  );
}
