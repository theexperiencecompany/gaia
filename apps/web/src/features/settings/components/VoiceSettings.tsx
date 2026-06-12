"use client";

import {
  Avatar,
  Button,
  Input,
  Select,
  SelectItem,
  type Selection,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@heroui/react";
import {
  CheckmarkCircle02Icon,
  FemaleSymbolIcon,
  Globe02Icon,
  MaleSymbolIcon,
  PauseIcon,
  PlayIcon,
  Search01Icon,
} from "@icons";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type { VoiceOption } from "@/features/settings/api/voiceApi";
import {
  useSelectVoice,
  useVoices,
} from "@/features/settings/hooks/useVoiceSettings";
import { cn } from "@/lib/utils";

const FLAG_CDN_BASE = "https://flagcdn.com/w80";

const flagUrl = (countryCode: string) =>
  `${FLAG_CDN_BASE}/${countryCode.toLowerCase()}.png`;

const ALL_FILTER = "all";

function GenderIcon({ gender }: { gender: string }) {
  if (gender === "Female") {
    return <FemaleSymbolIcon className="h-3.5 w-3.5 shrink-0 text-pink-400" />;
  }
  if (gender === "Male") {
    return <MaleSymbolIcon className="h-3.5 w-3.5 shrink-0 text-blue-400" />;
  }
  return null;
}

export default function VoiceSettings() {
  const { data, isLoading } = useVoices();
  const selectVoice = useSelectVoice();
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  // Typing stays instant; the (cheap but table-rebuilding) filter pass runs
  // at deferred priority so fast keystrokes never jank the input.
  const deferredSearch = useDeferredValue(search);
  const [genderFilter, setGenderFilter] = useState(ALL_FILTER);
  const [countryFilter, setCountryFilter] = useState(ALL_FILTER);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // One shared audio element; switching voices swaps its source.
  useEffect(() => {
    const audio = new Audio();
    audio.addEventListener("ended", () => setPlayingVoiceId(null));
    audioRef.current = audio;
    return () => {
      audio.pause();
      audioRef.current = null;
    };
  }, []);

  const togglePreview = useCallback(
    (voice: VoiceOption) => {
      const audio = audioRef.current;
      if (!audio || !voice.preview_url) return;
      if (playingVoiceId === voice.voice_id) {
        audio.pause();
        setPlayingVoiceId(null);
        return;
      }
      audio.src = voice.preview_url;
      audio
        .play()
        .then(() => setPlayingVoiceId(voice.voice_id))
        .catch(() => setPlayingVoiceId(null));
    },
    [playingVoiceId],
  );

  const selectedKeys = useMemo(
    () =>
      data?.selected_voice_id
        ? new Set([data.selected_voice_id])
        : new Set<string>(),
    [data?.selected_voice_id],
  );

  // Distinct filter options derived from the loaded voices.
  const genderOptions = useMemo(
    () => [...new Set((data?.voices ?? []).map((v) => v.gender))].sort(),
    [data?.voices],
  );
  // accent -> country_code so the dropdown can show the same flag as the rows.
  const countryOptions = useMemo(() => {
    const byAccent = new Map<string, string>();
    for (const v of data?.voices ?? []) {
      if (!byAccent.has(v.accent)) byAccent.set(v.accent, v.country_code);
    }
    return [...byAccent.entries()]
      .map(([accent, countryCode]) => ({ accent, countryCode }))
      .sort((a, b) => a.accent.localeCompare(b.accent));
  }, [data?.voices]);

  // Selection and playback are baked into the items so the table's cached
  // row nodes rebuild the instant either changes (optimistic select included)
  // — reading them from closure state would lag until the next refetch.
  const rows = useMemo(() => {
    const query = deferredSearch.trim().toLowerCase();
    return (data?.voices ?? [])
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
      }));
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
      }
    },
    [data?.selected_voice_id, selectVoice],
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

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Input
          aria-label="Search voices"
          placeholder="Search voices"
          value={search}
          onValueChange={setSearch}
          isClearable
          startContent={<Search01Icon className="h-4 w-4 text-zinc-500" />}
          className="sm:max-w-xs"
        />
        <Select
          aria-label="Filter by gender"
          placeholder="Gender"
          selectedKeys={[genderFilter]}
          onSelectionChange={(keys) =>
            setGenderFilter(String(Array.from(keys)[0] ?? ALL_FILTER))
          }
          startContent={
            genderFilter !== ALL_FILTER ? (
              <GenderIcon gender={genderFilter} />
            ) : undefined
          }
          className="sm:max-w-40"
        >
          {[
            <SelectItem key={ALL_FILTER}>All genders</SelectItem>,
            ...genderOptions.map((g) => <SelectItem key={g}>{g}</SelectItem>),
          ]}
        </Select>
        <Select
          aria-label="Filter by country"
          placeholder="Country"
          selectedKeys={[countryFilter]}
          onSelectionChange={(keys) =>
            setCountryFilter(String(Array.from(keys)[0] ?? ALL_FILTER))
          }
          startContent={(() => {
            // Show the chosen country's flag inline in the trigger, not
            // just inside the open list.
            if (countryFilter === ALL_FILTER) return undefined;
            const code = countryOptions.find(
              (c) => c.accent === countryFilter,
            )?.countryCode;
            return code ? (
              <Avatar
                src={flagUrl(code)}
                alt={`${countryFilter} flag`}
                className="h-4 w-4 shrink-0"
              />
            ) : (
              <Globe02Icon className="h-4 w-4 shrink-0 text-zinc-500" />
            );
          })()}
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

      <Table
        aria-label="Available voices"
        selectionMode="single"
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
                  <span className="text-sm text-zinc-400">
                    {voice.language}
                  </span>
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
                  <div
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
