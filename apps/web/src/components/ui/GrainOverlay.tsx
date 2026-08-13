import { cn } from "@/lib/utils";

/**
 * Fractal-noise tile rendered by the browser's own SVG filter, inlined as a
 * data URI so it costs no request and no decode. `stitchTiles` makes the tile
 * seamless when it repeats, which is what keeps the grain from showing a grid
 * on large surfaces.
 *
 * A single octave at a high base frequency is what makes this read as film
 * grain — stacking octaves sums low-frequency noise on top and the result is
 * cloudy haze instead of per-pixel speckle. `feColorMatrix` desaturates it,
 * because raw feTurbulence writes independent R/G/B and the colored speckle
 * tints whatever it sits on.
 */
const GRAIN_TILE =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160' viewBox='0 0 160 160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='1' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)'/%3E%3C/svg%3E\")";

/**
 * How the grain is composited. The two surfaces we put grain on need different
 * treatment, and picking the wrong one makes it invisible:
 *
 * - `photo` — detailed, mostly dark artwork. Overlay blending degrades to
 *   multiply against dark pixels, so the grain disappears into exactly the
 *   shadows it is meant to break up. Composite it normally instead, at a low
 *   opacity, which is what actually reads as film grain on a photograph.
 * - `surface` — smooth gradients and flat color. These show grain readily, and
 *   overlay is right here: it ties the speckle to the underlying hue instead
 *   of greying it out, and a much lower opacity is enough.
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
