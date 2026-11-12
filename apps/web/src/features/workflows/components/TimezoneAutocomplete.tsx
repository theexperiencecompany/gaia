"use client";

import { ComboBox, Input, ListBox } from "@heroui/react";
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
  const selectedCity = selected ? describeZone(selected.value).city : "";

  const [inputValue, setInputValue] = useState(selectedCity);
  // Keep the displayed text in sync when the timezone changes from outside.
  useEffect(() => {
    setInputValue(selectedCity);
  }, [selectedCity]);

  // Controlled `items` means the ComboBox shows exactly what we pass (no
  // built-in filtering), so we match across the full search text ourselves.
  // When the box just shows the current selection (or is empty), show everything.
  const filteredOptions = useMemo(() => {
    const query = inputValue.trim().toLowerCase();
    if (!query || query === selectedCity.toLowerCase()) return options;
    return options.filter((tz) =>
      timezoneSearchText(tz.value, tz.offset).includes(query),
    );
  }, [inputValue, options, selectedCity]);

  return (
    <ComboBox
      aria-label="Timezone"
      className={className}
      items={filteredOptions}
      inputValue={inputValue}
      onInputChange={setInputValue}
      selectedKey={timezone || null}
      onSelectionChange={(key) => {
        if (key) onChange(String(key));
      }}
    >
      <ComboBox.InputGroup>
        <Input />
        <ComboBox.Trigger />
      </ComboBox.InputGroup>
      <ComboBox.Popover className="min-w-fit">
        <ListBox>
          {(tz: TimezoneOption) => {
            const { city, region } = describeZone(tz.value);
            return (
              <ListBox.Item id={tz.value} textValue={city}>
                <div className="flex min-w-0 flex-col">
                  <span className="truncate">{city}</span>
                  {region ? (
                    <span className="truncate text-xs text-default-500">
                      {region}
                    </span>
                  ) : null}
                </div>
                <span className="ml-auto shrink-0 pl-4 text-xs tabular-nums text-default-500">
                  {tz.offset}
                </span>
                <ListBox.ItemIndicator />
              </ListBox.Item>
            );
          }}
        </ListBox>
      </ComboBox.Popover>
    </ComboBox>
  );
}
