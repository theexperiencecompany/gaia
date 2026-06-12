"use client";

import {
  Avatar,
  Input,
  Select,
  SelectItem,
  type Selection,
} from "@heroui/react";
import {
  FemaleSymbolIcon,
  Globe02Icon,
  MaleSymbolIcon,
  Search01Icon,
} from "@icons";
import { type ReactNode, useMemo } from "react";

import type { VoiceOption } from "@/features/settings/api/voiceApi";

const FLAG_CDN_BASE = "https://flagcdn.com/w80";

export const flagUrl = (countryCode: string) =>
  `${FLAG_CDN_BASE}/${countryCode.toLowerCase()}.png`;

export const ALL_FILTER = "all";

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

/** First key of a HeroUI single-select change, or the all-items fallback. */
const selectedFilterKey = (keys: Selection): string => {
  const key = keys === "all" ? undefined : Array.from(keys)[0];
  return typeof key === "string" ? key : ALL_FILTER;
};

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
      <Avatar
        src={flagUrl(code)}
        alt={`${countryFilter} flag`}
        className="h-4 w-4 shrink-0"
      />
    ) : (
      <Globe02Icon className="h-4 w-4 shrink-0 text-zinc-500" />
    );
  }

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <Input
        aria-label="Search voices"
        placeholder="Search voices"
        value={search}
        onValueChange={onSearchChange}
        isClearable
        startContent={<Search01Icon className="h-4 w-4 text-zinc-500" />}
        className="sm:max-w-xs"
      />
      <Select
        aria-label="Filter by gender"
        placeholder="Gender"
        selectedKeys={[genderFilter]}
        onSelectionChange={(keys) =>
          onGenderFilterChange(selectedFilterKey(keys))
        }
        startContent={
          genderFilter === ALL_FILTER ? undefined : (
            <GenderIcon gender={genderFilter} />
          )
        }
        className="sm:max-w-40"
      >
        {[
          <SelectItem key={ALL_FILTER}>All genders</SelectItem>,
          ...genderOptions.map((g) => (
            <SelectItem key={g} startContent={<GenderIcon gender={g} />}>
              {g}
            </SelectItem>
          )),
        ]}
      </Select>
      <Select
        aria-label="Filter by country"
        placeholder="Country"
        selectedKeys={[countryFilter]}
        onSelectionChange={(keys) =>
          onCountryFilterChange(selectedFilterKey(keys))
        }
        startContent={countryStartContent}
        className="sm:max-w-44"
      >
        {[
          <SelectItem
            key={ALL_FILTER}
            startContent={
              <Globe02Icon className="h-4 w-4 shrink-0 text-zinc-500" />
            }
          >
            All countries
          </SelectItem>,
          ...countryOptions.map(({ accent, countryCode }) => (
            <SelectItem
              key={accent}
              startContent={
                countryCode ? (
                  <Avatar
                    src={flagUrl(countryCode)}
                    alt={`${accent} flag`}
                    className="h-4 w-4 shrink-0"
                  />
                ) : (
                  <Globe02Icon className="h-4 w-4 shrink-0 text-zinc-500" />
                )
              }
            >
              {accent}
            </SelectItem>
          )),
        ]}
      </Select>
    </div>
  );
}
