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
  type TableProps,
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
import { useCallback, useDeferredValue, useMemo } from "react";
import type { VoiceOption } from "@/features/settings/api/voiceApi";
import {
  ALL_FILTER,
  flagUrl,
  GenderIcon,
} from "@/features/settings/components/VoiceFilters";
import { useVoicePreview } from "@/features/settings/hooks/useVoicePreview";
import {
  useSelectVoice,
  useStarVoice,
  useVoices,
} from "@/features/settings/hooks/useVoiceSettings";
import { cn } from "@/lib/utils";

interface VoiceTableProps {
  /** Substring filter on name/description (deferred so typing stays smooth). */
  search?: string;
  /** Gender value to filter on, or {@link ALL_FILTER} for no filter. */
  genderFilter?: string;
  /** Accent/country value to filter on, or {@link ALL_FILTER} for no filter. */
  countryFilter?: string;
  /** Show the Language column + multi-language chip. */
  showLanguage?: boolean;
  /** Show the trailing Preview play/pause column. */
  showPreview?: boolean;
  /** Play the sample when a row is selected. Off in live voice sessions. */
  previewOnSelect?: boolean;
  classNames?: TableProps["classNames"];
  "aria-label"?: string;
}

type VoiceRow = VoiceOption & { isSelected: boolean; isPlaying: boolean };

interface Column {
  key: string;
  label: string;
  align?: "end";
}

/**
 * The voice picker table shared by the settings page and the in-session
 * "Customise voice" popover. Owns its own data/selection/star/preview state;
 * callers only choose which columns to show and supply filter values.
 */
export function VoiceTable({
  search = "",
  genderFilter = ALL_FILTER,
  countryFilter = ALL_FILTER,
  showLanguage = true,
  showPreview = true,
  previewOnSelect = true,
  classNames,
  "aria-label": ariaLabel = "Available voices",
}: Readonly<VoiceTableProps>) {
  const { data, isLoading } = useVoices();
  const selectVoice = useSelectVoice();
  const starVoice = useStarVoice();
  const { playingVoiceId, playPreview, togglePreview } = useVoicePreview();
  // Typing stays instant; the (cheap but table-rebuilding) filter pass runs
  // at deferred priority so fast keystrokes never jank the input.
  const deferredSearch = useDeferredValue(search);

  const selectedKeys = useMemo(
    () =>
      data?.selected_voice_id
        ? new Set([data.selected_voice_id])
        : new Set<string>(),
    [data?.selected_voice_id],
  );

  // Variable columns: language/preview drop out in the compact in-session
  // picker. Built dynamically so react-aria's collection stays valid (it
  // rejects conditionally-null static children).
  const columns = useMemo<Column[]>(() => {
    const cols: Column[] = [
      { key: "voice", label: "Voice" },
      { key: "gender", label: "Gender" },
    ];
    if (showLanguage) cols.push({ key: "language", label: "Language" });
    cols.push({ key: "country", label: "Country" });
    if (showPreview)
      cols.push({ key: "preview", label: "Preview", align: "end" });
    return cols;
  }, [showLanguage, showPreview]);

  // Selection and playback are baked into the items so the table's cached
  // row nodes rebuild the instant either changes (optimistic select included)
  // — reading them from closure state would lag until the next refetch.
  const rows = useMemo<VoiceRow[]>(() => {
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
        // Hearing the choice confirms it — selecting also plays the sample,
        // except in a live session where it would clash with the agent.
        if (previewOnSelect) {
          const voice = data?.voices.find((v) => v.voice_id === voiceId);
          if (voice) playPreview(voice);
        }
      }
    },
    [
      data?.selected_voice_id,
      data?.voices,
      selectVoice,
      playPreview,
      previewOnSelect,
    ],
  );

  const renderCell = useCallback(
    (voice: VoiceRow, columnKey: string) => {
      switch (columnKey) {
        case "voice":
          return (
            <div className="flex min-w-0 items-center gap-2">
              {/* Star toggle — propagation stopped so starring never doubles
                  as selecting the row. */}
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
                    voice.starred && "text-yellow-400 hover:text-yellow-300",
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
                  <p className="truncate text-sm text-white">{voice.name}</p>
                  {voice.isSelected && (
                    <CheckmarkCircle02Icon className="h-4 w-4 shrink-0 text-primary" />
                  )}
                </div>
                <p className="mt-0.5 truncate text-xs text-zinc-500">
                  {voice.description}
                </p>
              </div>
            </div>
          );
        case "gender":
          return (
            <div className="flex items-center gap-1.5">
              <GenderIcon gender={voice.gender} />
              <span className="text-sm text-zinc-400">{voice.gender}</span>
            </div>
          );
        case "language":
          return (
            <div className="flex items-center gap-1.5">
              <span className="text-sm text-zinc-400">{voice.language}</span>
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
          );
        case "country":
          return (
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
              <span className="text-sm text-zinc-400">{voice.accent}</span>
            </div>
          );
        case "preview": {
          const PreviewIcon = voice.isPlaying ? PauseIcon : PlayIcon;
          return (
            // Stop pointer events here so playing a sample never doubles as
            // selecting the row.
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
                  voice.isPlaying
                    ? `Pause ${voice.name} preview`
                    : `Play ${voice.name} preview`
                }
                isDisabled={!voice.preview_url}
                className={cn(voice.isPlaying && "text-primary")}
                onPress={() => togglePreview(voice)}
              >
                <PreviewIcon className="h-4 w-4" />
              </Button>
            </div>
          );
        }
        default:
          return null;
      }
    },
    [starVoice, togglePreview],
  );

  return (
    <Table
      aria-label={ariaLabel}
      selectionMode="single"
      classNames={{ tr: "cursor-pointer", ...classNames }}
      disallowEmptySelection
      selectedKeys={selectedKeys}
      onSelectionChange={handleSelectionChange}
    >
      <TableHeader columns={columns}>
        {(column) => (
          <TableColumn
            key={column.key}
            className={column.align === "end" ? "text-right" : undefined}
          >
            {column.label}
          </TableColumn>
        )}
      </TableHeader>
      <TableBody
        items={rows}
        isLoading={isLoading}
        loadingContent={<Spinner size="sm" label="Loading voices" />}
        emptyContent={isLoading ? " " : "No voices match your filters"}
      >
        {(voice) => (
          <TableRow key={voice.voice_id} textValue={voice.name}>
            {(columnKey) => (
              <TableCell>{renderCell(voice, String(columnKey))}</TableCell>
            )}
          </TableRow>
        )}
      </TableBody>
    </Table>
  );
}
