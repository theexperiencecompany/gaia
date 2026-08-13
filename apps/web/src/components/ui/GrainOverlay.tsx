import { cn } from "@/lib/utils";

/**
 * Fractal-noise tile rendered by the browser's own SVG filter, inlined as a
 * data URI so it costs no request and no decode. `stitchTiles` makes the tile
 * seamless when it repeats, which is what keeps the grain from showing a grid
 * on large surfaces.
 */
const GRAIN_TILE =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160' viewBox='0 0 160 160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)'/%3E%3C/svg%3E\")";

interface GrainOverlayProps {
  /** Match the parent's radius so the grain is clipped to the same shape. */
  className?: string;
}

/**
 * Film-grain layer for images and large gradient surfaces — breaks up banding
 * and gives flat artwork a tactile, printed feel. Absolutely positioned, so
 * the parent must be positioned and should clip (`overflow-hidden` or a
 * matching radius on this element).
 */
export function GrainOverlay({ className }: GrainOverlayProps) {
  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-0 opacity-[0.05] mix-blend-overlay",
        className,
      )}
      style={{ backgroundImage: GRAIN_TILE }}
    />
  );
}
