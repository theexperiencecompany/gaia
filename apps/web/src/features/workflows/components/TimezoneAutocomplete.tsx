"use client";

import { Autocomplete, AutocompleteItem } from "@heroui/autocomplete";
import { useEffect, useMemo, useState } from "react";

import { timezoneSearchText } from "@/utils/timezoneUtils";

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
 * Searchable timezone picker. The query matches across city, country, region
 * and UTC offset (so "india", "+5:30", "asia" and "kolkata" all find
 * Asia/Kolkata); each option shows the city, its region, and the live offset.
 */
export function TimezoneAutocomplete({
  timezone,
  options,
  onChange,
  className,
}: TimezoneAutocompleteProps) {
  const selected = options.find((tz) => tz.value === timezone);
  const selectedOffset = selected?.offset;
  const selectedCity = selected ? describeZone(selected.value).city : "";

  const [inputValue, setInputValue] = useState(selectedCity);
  // Keep the displayed text in sync when the timezone changes from outside.
  useEffect(() => {
    setInputValue(selectedCity);
  }, [selectedCity]);

  // `items` (controlled) means HeroUI shows exactly what we pass — no built-in
  // filtering — so we match across the full search text ourselves. When the box
  // just shows the current selection (or is empty), show everything to browse.
  const filteredOptions = useMemo(() => {
    const query = inputValue.trim().toLowerCase();
    if (!query || query === selectedCity.toLowerCase()) return options;
    return options.filter((tz) =>
      timezoneSearchText(tz.value, tz.offset).includes(query),
    );
  }, [inputValue, options, selectedCity]);

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
      itemHeight={52}
      items={filteredOptions}
      inputValue={inputValue}
      onInputChange={setInputValue}
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
