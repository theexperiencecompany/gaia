import type React from "react";
import type { ReactNode } from "react";

interface DitherEffectProps {
  children: ReactNode;
  intensity?: number; // 0-100, controls the dither visibility
  scale?: number; // Controls the size of the dither pattern
}

export const DitherEffect: React.FC<DitherEffectProps> = ({
  children,
  intensity = 15,
  scale = 1,
}) => {
  // Generate a unique ID for this instance's SVG filter
  const filterId = `dither-${Math.random().toString(36).substr(2, 9)}`;

  return (
    <div className="relative">
      {/* SVG filter definition */}
      <svg className="absolute h-0 w-0" aria-hidden="true">
        <defs>
          <filter id={filterId}>
            {/* Create noise pattern */}
            <feTurbulence
              type="fractalNoise"
              baseFrequency={0.65 * scale}
              numOctaves={3}
              result="noise"
            />
            {/* Convert to black and white */}
            <feColorMatrix
              in="noise"
              type="saturate"
              values="0"
              result="monoNoise"
            />
            {/* Threshold to create dither pattern */}
            <feComponentTransfer in="monoNoise" result="dither">
              <feFuncA type="discrete" tableValues="0 1" />
            </feComponentTransfer>
            {/* Blend with original */}
            <feBlend
              in="SourceGraphic"
              in2="dither"
              mode="multiply"
              result="blend"
            />
            {/* Control opacity/intensity */}
            <feComponentTransfer in="blend">
              <feFuncA type="linear" slope={1 - intensity / 200} />
            </feComponentTransfer>
          </filter>
        </defs>
      </svg>

      {/* Apply filter to children */}
      <div style={{ filter: `url(#${filterId})` }}>{children}</div>
    </div>
  );
};
