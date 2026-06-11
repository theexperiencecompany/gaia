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
    <div className="grid grid-cols-3 gap-3 p-4 sm:grid-cols-4">
      {icons.map((icon) => {
        const isSelected = icon.id === selectedId;
        return (
          <button
            key={icon.id}
            type="button"
            onClick={() => onSelect(icon.id)}
            className={cn(
              "group flex flex-col items-center gap-2 rounded-2xl p-3 transition-colors",
              isSelected ? "bg-primary/10" : "hover:bg-white/5",
            )}
          >
            <div
              className={cn(
                "rounded-2xl p-0.5 transition-all",
                isSelected
                  ? "ring-2 ring-primary"
                  : "ring-2 ring-transparent group-hover:scale-105",
              )}
            >
              {/* Data-URL previews from the main process — not optimizable. */}
              {/* biome-ignore lint/performance/noImgElement: data-URL preview */}
              <img
                src={icon.preview}
                alt={`${icon.label} app icon`}
                className="size-16 rounded-xl object-contain"
              />
            </div>
            <span
              className={cn(
                "text-xs",
                isSelected ? "font-medium text-primary" : "text-zinc-400",
              )}
            >
              {icon.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
