"use client";

import { Autocomplete, Input, ListBox, SearchField } from "@heroui/react";
import { useEffect, useMemo, useState } from "react";

import { timezoneSearchText } from "@/utils/timezoneUtils";

interface TimezoneOption {
  value: string;
  label: string;
  offset: string;
}

export interface TimezoneAutocompleteProps {
  timezone: string;
  options: TimezoneOption[];
  onChange: (timezone: string) => void;
  className?: string;
}

// Split an IANA id ("Asia/Kolkata", "America/Argentina/Buenos_Aires") into a
// city (last segment) and its region path, both human-readable.
function describeZone(value: string): { city: string; region: string } {
  const parts = value.replaceAll("_", " ").split("/");
  const city = parts.at(-1) ?? value;
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
}: Readonly<TimezoneAutocompleteProps>) {
  const selected = options.find((tz) => tz.value === timezone);
  const selectedOffset = selected?.offset;
  const selectedCity = selected ? describeZone(selected.value).city : "";

  const [inputValue, setInputValue] = useState(selectedCity);
  // Keep the displayed text in sync when the timezone changes from outside.
  useEffect(() => {
    setInputValue(selectedCity);
  }, [selectedCity]);

  // The dropdown shows exactly what we pass (no built-in filtering) so we match
  // across the full search text ourselves. When the box just shows the current
  // selection (or is empty), show everything to browse.
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
      className={className}
      selectedKey={timezone || null}
      onSelectionChange={(key) => {
        if (key) onChange(String(key));
      }}
    >
      <Autocomplete.Trigger>
        {selectedOffset ? (
          <span className="shrink-0 text-xs text-zinc-500">
            {selectedOffset}
          </span>
        ) : null}
        <Autocomplete.Value />
        <Autocomplete.Indicator />
      </Autocomplete.Trigger>
      <Autocomplete.Popover className="min-w-[var(--trigger-width)]">
        <Autocomplete.Filter filter={() => true}>
          <SearchField
            aria-label="Search timezones"
            value={inputValue}
            onChange={setInputValue}
          >
            <Input placeholder="Search timezones..." />
          </SearchField>
          <ListBox aria-label="Timezones">
            {filteredOptions.map((tz) => {
              const { city, region } = describeZone(tz.value);
              return (
                <ListBox.Item key={tz.value} id={tz.value} textValue={city}>
                  <div className="flex w-full items-center justify-between gap-2">
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate">{city}</span>
                      {region ? (
                        <span className="truncate text-xs text-default-500">
                          {region}
                        </span>
                      ) : null}
                    </div>
                    <span className="shrink-0 text-xs tabular-nums text-default-500">
                      {tz.offset}
                    </span>
                  </div>
                </ListBox.Item>
              );
            })}
          </ListBox>
        </Autocomplete.Filter>
      </Autocomplete.Popover>
    </Autocomplete>
  );
}
