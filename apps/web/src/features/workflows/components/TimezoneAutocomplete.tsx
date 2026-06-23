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
            endContent={tz.offset}
          >
            {city}
          </AutocompleteItem>
        );
      }}
    </Autocomplete>
  );
}
