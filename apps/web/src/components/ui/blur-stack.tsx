import type { CSSProperties } from "react";

export interface BlurLayer {
  blur: number;
  maskStops: [number, number, number, number]; // [fadeInStart, solidStart, solidEnd, fadeOutEnd]
  zIndex: number;
}

const DEFAULT_BLUR_CONFIG: BlurLayer[] = [
  { blur: 0.5, maskStops: [0, 12.5, 25, 37.5], zIndex: 1 },
  { blur: 1, maskStops: [12.5, 25, 37.5, 50], zIndex: 2 },
  { blur: 2, maskStops: [25, 37.5, 50, 62.5], zIndex: 3 },
  { blur: 4, maskStops: [37.5, 50, 62.5, 75], zIndex: 4 },
  { blur: 8, maskStops: [50, 62.5, 75, 87.5], zIndex: 5 },
  { blur: 16, maskStops: [62.5, 75, 87.5, 100], zIndex: 6 },
  { blur: 32, maskStops: [75, 87.5, 100, 100], zIndex: 7 },
  { blur: 64, maskStops: [87.5, 100, 100, 100], zIndex: 8 },
];

// Per-layer alpha veil. Built here (not inline) because the gradient's
// black/transparent stops are structural mask alpha, not theme colors;
// consumed below through vars so only measured values stay in `style`.
function maskImageFor(maskStops: BlurLayer["maskStops"]): string {
  const [start, solidStart, solidEnd, end] = maskStops;
  return `linear-gradient(rgba(0,0,0,0) ${start}%, rgb(0,0,0) ${solidStart}%, rgb(0,0,0) ${solidEnd}%, rgba(0,0,0,0) ${end}%)`;
}

export default function BlurStack({
  className,
  config = DEFAULT_BLUR_CONFIG,
}: {
  className?: string;
  config?: BlurLayer[];
}) {
  return (
    <div className={className}>
      <div className="absolute inset-0 overflow-hidden">
        {config.map((layer, index) => {
          return (
            <div
              // biome-ignore lint/suspicious/noArrayIndexKey: static stack
              key={index}
              className="pointer-events-none absolute inset-0 rounded-none opacity-100 [mask-image:var(--blur-mask)] [backdrop-filter:blur(var(--blur-amount))] [-webkit-backdrop-filter:blur(var(--blur-amount))]"
              style={
                {
                  zIndex: layer.zIndex,
                  "--blur-mask": maskImageFor(layer.maskStops),
                  "--blur-amount": `${layer.blur}px`,
                } as CSSProperties
              }
            />
          );
        })}
      </div>
    </div>
  );
}
