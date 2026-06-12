"use client";

import {
  Avatar,
  Button,
  type Selection,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@heroui/react";
import { CheckmarkCircle02Icon, PauseIcon, PlayIcon } from "@icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { VoiceOption } from "@/features/settings/api/voiceApi";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import {
  useSelectVoice,
  useVoices,
} from "@/features/settings/hooks/useVoiceSettings";
import { cn } from "@/lib/utils";

const FLAG_CDN_BASE = "https://flagcdn.com/w80";

const flagUrl = (countryCode: string) =>
  `${FLAG_CDN_BASE}/${countryCode.toLowerCase()}.png`;

export default function VoiceSettings() {
  const { data, isLoading } = useVoices();
  const selectVoice = useSelectVoice();
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);
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

  // Selection and playback are baked into the items so the table's cached
  // row nodes rebuild the instant either changes (optimistic select included)
  // — reading them from closure state would lag until the next refetch.
  const rows = useMemo(
    () =>
      (data?.voices ?? []).map((voice) => ({
        ...voice,
        isSelected: voice.voice_id === data?.selected_voice_id,
        isPlaying: voice.voice_id === playingVoiceId,
      })),
    [data?.voices, data?.selected_voice_id, playingVoiceId],
  );

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
    <SettingsPage>
      <div>
        <h1 className="text-lg font-medium text-white">Voice</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Choose the voice GAIA speaks with in voice mode. Play a sample, then
          select a row to make it yours.
        </p>
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
          <TableColumn>Language</TableColumn>
          <TableColumn>Country</TableColumn>
          <TableColumn className="text-right">Preview</TableColumn>
        </TableHeader>
        <TableBody
          items={rows}
          isLoading={isLoading}
          loadingContent={<Spinner size="sm" label="Loading voices" />}
          emptyContent={isLoading ? " " : "No voices available"}
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
                  <span className="text-sm text-zinc-400">
                    {voice.language}
                  </span>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Avatar
                      src={flagUrl(voice.country_code)}
                      alt={`${voice.accent} flag`}
                      className="h-5 w-5 shrink-0"
                    />
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
    </SettingsPage>
  );
}
