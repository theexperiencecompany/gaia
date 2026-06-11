"use client";

import type { DesktopAppIconOption } from "@shared/desktop-tools";
import { cn } from "@/lib/utils";

interface AppIconPickerProps {
  icons: DesktopAppIconOption[];
  selectedId: string;
  onSelect: (id: string) => void;
}

/** Arc-style app icon picker: preview grid, click to apply instantly. */
export function AppIconPicker({
  icons,
  selectedId,
  onSelect,
}: AppIconPickerProps) {
  return (
    <div className="grid grid-cols-4 gap-3 p-4 sm:grid-cols-5">
      {icons.map((icon) => {
        const isSelected = icon.id === selectedId;
        return (
          <button
            key={icon.id}
            type="button"
            aria-label={`${icon.label} app icon`}
            onClick={() => onSelect(icon.id)}
            className={cn(
              // 22% radius ≈ the macOS app-icon squircle, so flat square
              // sources match the default (pre-rounded) GAIA icon.
              "aspect-square overflow-hidden rounded-[24%] p-1 transition-all",
              isSelected
                ? "ring-2 ring-primary"
                : "ring-2 ring-transparent hover:scale-105",
            )}
          >
            {/* Data-URL previews from the main process — not optimizable. */}
            {/* biome-ignore lint/performance/noImgElement: data-URL preview */}
            <img
              src={icon.preview}
              alt={`${icon.label} app icon`}
              className="aspect-square h-full w-full rounded-[22%] object-cover"
            />
          </button>
        );
      })}
    </div>
  );
}
