"use client";

import { Button, Chip, Skeleton } from "@heroui/react";
import { CheckmarkCircle02Icon, PauseIcon, PlayIcon } from "@icons";
import { useCallback, useEffect, useRef, useState } from "react";

import type { VoiceOption } from "@/features/settings/api/voiceApi";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import {
  useSelectVoice,
  useVoices,
} from "@/features/settings/hooks/useVoiceSettings";
import { cn } from "@/lib/utils";

const ROW_GRID = "grid grid-cols-[1fr_6rem_7rem_2.5rem] items-center gap-3";

function VoiceRow({
  voice,
  isSelected,
  isPlaying,
  onSelect,
  onTogglePreview,
}: {
  voice: VoiceOption;
  isSelected: boolean;
  isPlaying: boolean;
  onSelect: () => void;
  onTogglePreview: () => void;
}) {
  const PreviewIcon = isPlaying ? PauseIcon : PlayIcon;

  return (
    <div
      className={cn(
        "group flex items-center gap-3 px-4 py-3 transition-colors",
        isSelected ? "bg-primary/5" : "hover:bg-zinc-800/60",
      )}
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
        className={cn(
          "shrink-0 bg-zinc-800 text-zinc-300",
          isPlaying && "bg-primary/20 text-primary",
        )}
        onPress={onTogglePreview}
      >
        <PreviewIcon className="h-4 w-4" />
      </Button>

      {/* The label + hidden radio make the rest of the row one accessible,
          keyboard-operable selection control (the play button stays separate
          so previewing never selects). */}
      <label className={cn(ROW_GRID, "min-w-0 flex-1 cursor-pointer")}>
        <input
          type="radio"
          name="gaia-voice"
          className="sr-only"
          checked={isSelected}
          onChange={onSelect}
        />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm text-white">{voice.name}</p>
            {isSelected && (
              <CheckmarkCircle02Icon className="h-4 w-4 shrink-0 text-primary" />
            )}
          </div>
          <p className="truncate text-xs text-zinc-500">{voice.description}</p>
        </div>

        <p className="text-sm text-zinc-400">{voice.language}</p>

        <div>
          <Chip size="sm" variant="flat" className="bg-zinc-800 text-zinc-300">
            {voice.accent}
          </Chip>
        </div>

        <p className="text-right text-xs text-zinc-500">{voice.country_code}</p>
      </label>
    </div>
  );
}

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

  const handleSelect = useCallback(
    (voice: VoiceOption) => {
      if (data?.selected_voice_id === voice.voice_id) return;
      selectVoice.mutate(voice.voice_id);
    },
    [data?.selected_voice_id, selectVoice],
  );

  return (
    <SettingsPage>
      <div>
        <h1 className="text-lg font-medium text-white">Voice</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Choose the voice GAIA speaks with in voice mode. Tap a row to use that
          voice, or play a sample first.
        </p>
      </div>

      <SettingsSection title="Available voices">
        <div className="flex items-center gap-3 px-4 py-2.5 text-xs font-medium uppercase tracking-wider text-zinc-500">
          <div className="w-8 shrink-0" />
          <div className={cn(ROW_GRID, "min-w-0 flex-1")}>
            <p>Voice</p>
            <p>Language</p>
            <p>Accent</p>
            <p className="text-right">Region</p>
          </div>
        </div>

        {isLoading &&
          Array.from({ length: 6 }, (_, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder list
            <div key={i} className="flex items-center gap-3 px-4 py-3">
              <Skeleton className="h-8 w-8 shrink-0 rounded-full" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-3 w-24 rounded-md" />
                <Skeleton className="h-2.5 w-48 rounded-md" />
              </div>
            </div>
          ))}

        {!isLoading &&
          data?.voices.map((voice) => (
            <VoiceRow
              key={voice.voice_id}
              voice={voice}
              isSelected={data.selected_voice_id === voice.voice_id}
              isPlaying={playingVoiceId === voice.voice_id}
              onSelect={() => handleSelect(voice)}
              onTogglePreview={() => togglePreview(voice)}
            />
          ))}
      </SettingsSection>
    </SettingsPage>
  );
}
