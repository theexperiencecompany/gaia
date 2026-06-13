"use client";

import { useState } from "react";

import {
  ALL_FILTER,
  VoiceFilters,
} from "@/features/settings/components/VoiceFilters";
import { VoiceTable } from "@/features/settings/components/VoiceTable";
import { useVoices } from "@/features/settings/hooks/useVoiceSettings";

export default function VoiceSettings() {
  const { data } = useVoices();
  const [search, setSearch] = useState("");
  const [genderFilter, setGenderFilter] = useState(ALL_FILTER);
  const [countryFilter, setCountryFilter] = useState(ALL_FILTER);

  return (
    // Wider than SettingsPage's max-w-2xl: five columns need the room —
    // constrained, the trailing Preview column clips out of view.
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <div>
        <h1 className="text-lg font-medium text-white">Voice</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Choose the voice GAIA speaks with in voice mode. Play a sample, then
          select a row to make it yours.
        </p>
      </div>

      <VoiceFilters
        voices={data?.voices ?? []}
        search={search}
        onSearchChange={setSearch}
        genderFilter={genderFilter}
        onGenderFilterChange={setGenderFilter}
        countryFilter={countryFilter}
        onCountryFilterChange={setCountryFilter}
      />

      <VoiceTable
        search={search}
        genderFilter={genderFilter}
        countryFilter={countryFilter}
      />
    </div>
  );
}
