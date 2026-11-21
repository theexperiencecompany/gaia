"use client";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { ALL } from "./useExplore";

/** What people hand to GAIA, as plain words in one line; the current one is the only cyan on the page. */
export function CategoryBar({
  categories,
  value,
  onChange,
}: {
  categories: string[];
  value: string;
  onChange: (category: string) => void;
}) {
  return (
    <fieldset
      aria-label="Category"
      className="no-scrollbar -mx-5 flex min-w-0 gap-0.5 overflow-x-auto px-5 sm:mx-0 sm:flex-wrap sm:px-0"
    >
      {[ALL, ...categories].map((category) => {
        const isSelected = value === category;
        return (
          <GaiaButton
            key={category}
            size="sm"
            variant="quiet"
            shape="md"
            tone={isSelected ? "accent" : "muted"}
            hoverTone={isSelected ? "accent" : "bright"}
            inset="tight"
            aria-pressed={isSelected}
            onPress={() => onChange(category)}
            className="h-9 min-w-0 shrink-0 text-sm"
          >
            {category === ALL ? "All" : category}
          </GaiaButton>
        );
      })}
    </fieldset>
  );
}
