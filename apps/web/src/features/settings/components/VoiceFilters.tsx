"use client";

import {
  Autocomplete,
  Avatar,
  ListBox,
  SearchField,
  Select,
} from "@heroui/react";
import {
  FemaleSymbolIcon,
  Globe02Icon,
  MaleSymbolIcon,
  Search01Icon,
} from "@icons";
import { type ReactNode, useMemo, useState } from "react";

import type { VoiceOption } from "@/features/settings/api/voiceApi";
import {
  ALL_FILTER,
  flagUrl,
} from "@/features/settings/utils/voiceFiltersData";

export function GenderIcon({ gender }: Readonly<{ gender: string }>) {
  if (gender === "Female") {
    return <FemaleSymbolIcon className="h-3.5 w-3.5 shrink-0 text-pink-400" />;
  }
  if (gender === "Male") {
    return <MaleSymbolIcon className="h-3.5 w-3.5 shrink-0 text-blue-400" />;
  }
  return null;
}

interface VoiceFiltersProps {
  voices: VoiceOption[];
  search: string;
  onSearchChange: (value: string) => void;
  genderFilter: string;
  onGenderFilterChange: (value: string) => void;
  countryFilter: string;
  onCountryFilterChange: (value: string) => void;
}

/** Search box + gender/country dropdowns above the voice table. */
export function VoiceFilters({
  voices,
  search,
  onSearchChange,
  genderFilter,
  onGenderFilterChange,
  countryFilter,
  onCountryFilterChange,
}: Readonly<VoiceFiltersProps>) {
  const [countryQuery, setCountryQuery] = useState("");
  // Distinct filter options derived from the loaded voices.
  const genderOptions = useMemo(
    () =>
      [...new Set(voices.map((v) => v.gender))].sort((a, b) =>
        a.localeCompare(b),
      ),
    [voices],
  );
  // accent -> country_code so the dropdown can show the same flag as the rows.
  const countryOptions = useMemo(() => {
    const byAccent = new Map<string, string>();
    for (const v of voices) {
      if (!byAccent.has(v.accent)) byAccent.set(v.accent, v.country_code);
    }
    return [...byAccent.entries()]
      .map(([accent, countryCode]) => ({ accent, countryCode }))
      .sort((a, b) => a.accent.localeCompare(b.accent));
  }, [voices]);

  // Resolved ahead of the JSX so the trigger content is a plain expression,
  // not a component defined inline in the render tree. Shows the chosen
  // country's flag inline in the trigger, not just inside the open list.
  let countryStartContent: ReactNode;
  if (countryFilter !== ALL_FILTER) {
    const code = countryOptions.find(
      (c) => c.accent === countryFilter,
    )?.countryCode;
    countryStartContent = code ? (
      <Avatar className="h-4 w-4 shrink-0">
        <Avatar.Image src={flagUrl(code)} alt={`${countryFilter} flag`} />
        <Avatar.Fallback />
      </Avatar>
    ) : (
      <Globe02Icon className="h-4 w-4 shrink-0 text-zinc-500" />
    );
  }

  const genderLabel =
    genderFilter === ALL_FILTER ? "All genders" : genderFilter;

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <SearchField
        aria-label="Search voices"
        value={search}
        onChange={onSearchChange}
        className="sm:max-w-xs"
      >
        <SearchField.Group>
          <Search01Icon className="h-4 w-4 text-zinc-500" />
          <SearchField.Input placeholder="Search voices" />
          <SearchField.ClearButton />
        </SearchField.Group>
      </SearchField>
      <Select
        aria-label="Filter by gender"
        selectedKey={genderFilter}
        onSelectionChange={(key) =>
          onGenderFilterChange(typeof key === "string" ? key : ALL_FILTER)
        }
        className="sm:max-w-40"
      >
        <Select.Trigger>
          {genderFilter === ALL_FILTER ? null : (
            <GenderIcon gender={genderFilter} />
          )}
          <Select.Value>{genderLabel}</Select.Value>
          <Select.Indicator />
        </Select.Trigger>
        <Select.Popover>
          <ListBox>
            <ListBox.Item id={ALL_FILTER} textValue="All genders">
              All genders
            </ListBox.Item>
            {genderOptions.map((g) => (
              <ListBox.Item key={g} id={g} textValue={g}>
                <GenderIcon gender={g} />
                {g}
              </ListBox.Item>
            ))}
          </ListBox>
        </Select.Popover>
      </Select>
      <Autocomplete
        aria-label="Filter by country"
        selectedKey={countryFilter}
        onSelectionChange={(key) =>
          onCountryFilterChange(typeof key === "string" ? key : ALL_FILTER)
        }
        className="sm:max-w-44"
      >
        <Autocomplete.Trigger>
          {countryStartContent}
          <Autocomplete.Value />
          <Autocomplete.Indicator />
        </Autocomplete.Trigger>
        <Autocomplete.Popover>
          <Autocomplete.Filter>
            <SearchField
              aria-label="Search countries"
              value={countryQuery}
              onChange={setCountryQuery}
            >
              <SearchField.Input placeholder="Country" />
            </SearchField>
            <ListBox aria-label="Countries">
              <ListBox.Item id={ALL_FILTER} textValue="All countries">
                <Globe02Icon className="h-4 w-4 shrink-0 text-zinc-500" />
                All countries
              </ListBox.Item>
              {countryOptions.map(({ accent, countryCode }) => (
                <ListBox.Item key={accent} id={accent} textValue={accent}>
                  {countryCode ? (
                    <Avatar className="h-4 w-4 shrink-0">
                      <Avatar.Image
                        src={flagUrl(countryCode)}
                        alt={`${accent} flag`}
                      />
                      <Avatar.Fallback />
                    </Avatar>
                  ) : (
                    <Globe02Icon className="h-4 w-4 shrink-0 text-zinc-500" />
                  )}
                  {accent}
                </ListBox.Item>
              ))}
            </ListBox>
          </Autocomplete.Filter>
        </Autocomplete.Popover>
      </Autocomplete>
    </div>
  );
}
