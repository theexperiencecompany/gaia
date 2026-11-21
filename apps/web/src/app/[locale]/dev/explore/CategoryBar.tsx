"use client";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { cn } from "@/lib/utils";
import { ALL } from "./useExplore";

interface CategoryPickerProps {
  categories: string[];
  value: string;
  onChange: (category: string) => void;
}

function CategoryButton({
  label,
  isSelected,
  onPress,
  className,
}: {
  label: string;
  isSelected: boolean;
  onPress: () => void;
  className?: string;
}) {
  return (
    <GaiaButton
      size="sm"
      variant="quiet"
      tone={isSelected ? "accent" : "muted"}
      hoverTone={isSelected ? "accent" : "bright"}
      inset="tight"
      aria-pressed={isSelected}
      onPress={onPress}
      className={cn("h-9 min-w-0 shrink-0 text-sm", className)}
    >
      {label}
    </GaiaButton>
  );
}

/** What people hand to GAIA, as plain words in one line; the current one is the only cyan on the page. */
export function CategoryBar({
  categories,
  value,
  onChange,
}: CategoryPickerProps) {
  return (
    <fieldset
      aria-label="Category"
      className="no-scrollbar min-w-0 -mx-5 flex gap-0.5 overflow-x-auto px-5 sm:mx-0 sm:flex-wrap sm:px-0"
    >
      {[ALL, ...categories].map((category) => (
        <CategoryButton
          key={category}
          label={category === ALL ? "All" : category}
          isSelected={value === category}
          onPress={() => onChange(category)}
        />
      ))}
    </fieldset>
  );
}

/** Sketch B: the same choice as a left rail. */
export function CategoryRail({
  categories,
  value,
  onChange,
}: CategoryPickerProps) {
  return (
    <fieldset aria-label="Category" className="flex min-w-0 flex-col gap-0.5">
      {[ALL, ...categories].map((category) => (
        <CategoryButton
          key={category}
          label={category === ALL ? "All" : category}
          isSelected={value === category}
          onPress={() => onChange(category)}
          className="w-full justify-start"
        />
      ))}
    </fieldset>
  );
}
