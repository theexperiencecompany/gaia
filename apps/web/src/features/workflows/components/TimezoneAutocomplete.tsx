"use client";

import { Autocomplete, AutocompleteItem } from "@heroui/autocomplete";

interface TimezoneOption {
  value: string;
  label: string;
  offset: string;
}

interface TimezoneAutocompleteProps {
  timezone: string;
  options: TimezoneOption[];
  onChange: (timezone: string) => void;
  className?: string;
}

// Split an IANA id ("Asia/Kolkata", "America/Argentina/Buenos_Aires") into a
// city (last segment) and its region path, both human-readable.
function describeZone(value: string): { city: string; region: string } {
  const parts = value.replace(/_/g, " ").split("/");
  const city = parts[parts.length - 1] ?? value;
  const region = parts.slice(0, -1).join(" / ");
  return { city, region };
}

/**
 * Searchable timezone picker. Each option shows the city, its IANA region path,
 * and the live UTC offset (e.g. "Kolkata — Asia · +05:30"); the trigger shows
 * the canonical "Region/City" with the offset alongside.
 */
export function TimezoneAutocomplete({
  timezone,
  options,
  onChange,
  className,
}: TimezoneAutocompleteProps) {
  const selectedOffset = options.find((tz) => tz.value === timezone)?.offset;

  return (
    <Autocomplete
      aria-label="Timezone"
      size="sm"
      className={className}
      // Let the dropdown size to its content (zone + region + offset) instead of
      // being clamped to the narrow trigger width, so nothing is cut off.
      popoverProps={{ classNames: { content: "min-w-fit" } }}
      // The list is virtualized with a fixed row height (default 32px), which is
      // too short for the two-line city + region item and made rows overlap.
      // Size the row to fit both lines so HeroUI's native description renders cleanly.
      itemHeight={52}
      defaultItems={options}
      selectedKey={timezone || null}
      onSelectionChange={(key) => {
        if (key) onChange(String(key));
      }}
      endContent={
        selectedOffset ? (
          <span className="shrink-0 text-xs text-zinc-500">
            {selectedOffset}
          </span>
        ) : null
      }
    >
      {(tz) => {
        const { city, region } = describeZone(tz.value);
        return (
          <AutocompleteItem
            key={tz.value}
            // textValue (the search key + selected input text) is the city; the
            // region is HeroUI's native description line, the offset its endContent.
            textValue={city}
            description={region || undefined}
            endContent={
              <span className="text-xs tabular-nums text-default-500">
                {tz.offset}
              </span>
            }
          >
            {city}
          </AutocompleteItem>
        );
      }}
    </Autocomplete>
  );
}
