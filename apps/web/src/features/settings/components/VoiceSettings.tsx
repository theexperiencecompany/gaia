"use client";

import {
  Avatar,
  Button,
  Chip,
  type Selection,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
  Tooltip,
} from "@heroui/react";
import {
  CheckmarkCircle02Icon,
  Globe02Icon,
  PauseIcon,
  PlayIcon,
  StarIcon,
} from "@icons";
import { useCallback, useDeferredValue, useMemo, useState } from "react";

import {
  ALL_FILTER,
  flagUrl,
  GenderIcon,
  VoiceFilters,
} from "@/features/settings/components/VoiceFilters";
import { useVoicePreview } from "@/features/settings/hooks/useVoicePreview";
import {
  useSelectVoice,
  useStarVoice,
  useVoices,
} from "@/features/settings/hooks/useVoiceSettings";
import { cn } from "@/lib/utils";

export default function VoiceSettings() {
  const { data, isLoading } = useVoices();
  const selectVoice = useSelectVoice();
  const starVoice = useStarVoice();
  const { playingVoiceId, playPreview, togglePreview } = useVoicePreview();
  const [search, setSearch] = useState("");
  // Typing stays instant; the (cheap but table-rebuilding) filter pass runs
  // at deferred priority so fast keystrokes never jank the input.
  const deferredSearch = useDeferredValue(search);
  const [genderFilter, setGenderFilter] = useState(ALL_FILTER);
  const [countryFilter, setCountryFilter] = useState(ALL_FILTER);

  const selectedKeys = useMemo(
    () =>
      data?.selected_voice_id
        ? new Set([data.selected_voice_id])
        : new Set<string>(),
    [data?.selected_voice_id],
  );

  // Selection and playback are baked into the items so the table's cached
  // row nodes rebuild the instant either changes (optimistic select included)
  // — reading them from closure state would lag until the next refetch.
  const rows = useMemo(() => {
    const query = deferredSearch.trim().toLowerCase();
    return (
      (data?.voices ?? [])
        .filter((voice) => {
          if (genderFilter !== ALL_FILTER && voice.gender !== genderFilter) {
            return false;
          }
          if (countryFilter !== ALL_FILTER && voice.accent !== countryFilter) {
            return false;
          }
          if (
            query &&
            !voice.name.toLowerCase().includes(query) &&
            !voice.description.toLowerCase().includes(query)
          ) {
            return false;
          }
          return true;
        })
        .map((voice) => ({
          ...voice,
          isSelected: voice.voice_id === data?.selected_voice_id,
          isPlaying: voice.voice_id === playingVoiceId,
        }))
        // Starred first (the backend already orders this way; re-sorting here
        // makes optimistic star toggles float instantly).
        .sort((a, b) => Number(b.starred) - Number(a.starred))
    );
  }, [
    data?.voices,
    data?.selected_voice_id,
    playingVoiceId,
    deferredSearch,
    genderFilter,
    countryFilter,
  ]);

  const handleSelectionChange = useCallback(
    (keys: Selection) => {
      if (keys === "all") return;
      const voiceId = Array.from(keys)[0];
      if (typeof voiceId === "string" && voiceId !== data?.selected_voice_id) {
        selectVoice.mutate(voiceId);
        // Hearing the choice confirms it — selecting also plays the sample.
        const voice = data?.voices.find((v) => v.voice_id === voiceId);
        if (voice) playPreview(voice);
      }
    },
    [data?.selected_voice_id, data?.voices, selectVoice, playPreview],
  );

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

      <Table
        aria-label="Available voices"
        selectionMode="single"
        classNames={{ tr: "cursor-pointer" }}
        disallowEmptySelection
        selectedKeys={selectedKeys}
        onSelectionChange={handleSelectionChange}
      >
        <TableHeader>
          <TableColumn>Voice</TableColumn>
          <TableColumn>Gender</TableColumn>
          <TableColumn>Language</TableColumn>
          <TableColumn>Country</TableColumn>
          <TableColumn className="text-right">Preview</TableColumn>
        </TableHeader>
        <TableBody
          items={rows}
          isLoading={isLoading}
          loadingContent={<Spinner size="sm" label="Loading voices" />}
          emptyContent={isLoading ? " " : "No voices match your filters"}
        >
          {(voice) => {
            const { isSelected, isPlaying } = voice;
            const PreviewIcon = isPlaying ? PauseIcon : PlayIcon;
            return (
              <TableRow key={voice.voice_id} textValue={voice.name}>
                <TableCell>
                  <div className="flex min-w-0 items-center gap-2">
                    {/* Star toggle — propagation stopped so starring never
                        doubles as selecting the row. */}
                    {/* biome-ignore lint/a11y/noStaticElementInteractions: propagation guard, not an interactive control */}
                    <div // NOSONAR S6848: propagation guard around the interactive Button below, not a control itself
                      onClick={(e) => e.stopPropagation()}
                      onPointerDown={(e) => e.stopPropagation()}
                      onPointerUp={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}
                    >
                      <Button
                        isIconOnly
                        size="sm"
                        radius="full"
                        variant="light"
                        aria-label={
                          voice.starred
                            ? `Unstar ${voice.name}`
                            : `Star ${voice.name}`
                        }
                        className={cn(
                          "text-zinc-600 hover:text-zinc-300",
                          voice.starred &&
                            "text-yellow-400 hover:text-yellow-300",
                        )}
                        onPress={() =>
                          starVoice.mutate({
                            voiceId: voice.voice_id,
                            starred: !voice.starred,
                          })
                        }
                      >
                        <StarIcon className="h-4 w-4" />
                      </Button>
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <p className="truncate text-sm text-white">
                          {voice.name}
                        </p>
                        {isSelected && (
                          <CheckmarkCircle02Icon className="h-4 w-4 shrink-0 text-primary" />
                        )}
                      </div>
                      <p className="mt-0.5 truncate text-xs text-zinc-500">
                        {voice.description}
                      </p>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1.5">
                    <GenderIcon gender={voice.gender} />
                    <span className="text-sm text-zinc-400">
                      {voice.gender}
                    </span>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm text-zinc-400">
                      {voice.language}
                    </span>
                    {voice.languages.length > 1 && (
                      <Tooltip
                        content={
                          <div className="max-w-56 px-1 py-1.5 text-xs">
                            {voice.languages.join(", ")}
                          </div>
                        }
                      >
                        <Chip
                          size="sm"
                          variant="flat"
                          className="cursor-default bg-zinc-800 text-zinc-400"
                        >
                          +{voice.languages.length - 1}
                        </Chip>
                      </Tooltip>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    {voice.country_code ? (
                      <Avatar
                        src={flagUrl(voice.country_code)}
                        alt={`${voice.accent} flag`}
                        className="h-5 w-5 shrink-0"
                      />
                    ) : (
                      <Globe02Icon className="h-5 w-5 shrink-0 text-zinc-500" />
                    )}
                    <span className="text-sm text-zinc-400">
                      {voice.accent}
                    </span>
                  </div>
                </TableCell>
                <TableCell>
                  {/* Stop pointer events here so playing a sample never
                      doubles as selecting the row. */}
                  {/* biome-ignore lint/a11y/noStaticElementInteractions: propagation guard, not an interactive control */}
                  <div // NOSONAR S6848: propagation guard around the interactive Button below, not a control itself
                    className="flex justify-end"
                    onClick={(e) => e.stopPropagation()}
                    onPointerDown={(e) => e.stopPropagation()}
                    onPointerUp={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    <Button
                      isIconOnly
                      size="sm"
                      radius="full"
                      variant="flat"
                      aria-label={
                        isPlaying
                          ? `Pause ${voice.name} preview`
                          : `Play ${voice.name} preview`
                      }
                      isDisabled={!voice.preview_url}
                      className={cn(isPlaying && "text-primary")}
                      onPress={() => togglePreview(voice)}
                    >
                      <PreviewIcon className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          }}
        </TableBody>
      </Table>
    </div>
  );
}
