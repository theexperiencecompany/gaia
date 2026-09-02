"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { VoiceOption } from "@/features/settings/api/voiceApi";

/**
 * Owns the single shared `<audio>` element for voice previews. Switching
 * voices swaps its source; `playingVoiceId` tracks what is audible so rows
 * can flip their play/pause affordance.
 */
export function useVoicePreview() {
  const [playingVoiceId, setPlayingVoiceId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const audio = new Audio();
    const handleEnded = () => setPlayingVoiceId(null);
    audio.addEventListener("ended", handleEnded);
    audioRef.current = audio;
    return () => {
      audio.removeEventListener("ended", handleEnded);
      audio.pause();
      audioRef.current = null;
    };
  }, []);

  const playPreview = useCallback((voice: VoiceOption) => {
    const audio = audioRef.current;
    if (!audio || !voice.preview_url) return;
    audio.src = voice.preview_url;
    audio
      .play()
      .then(() => setPlayingVoiceId(voice.voice_id))
      .catch(() => setPlayingVoiceId(null));
  }, []);

  const togglePreview = useCallback(
    (voice: VoiceOption) => {
      if (playingVoiceId === voice.voice_id) {
        audioRef.current?.pause();
        setPlayingVoiceId(null);
        return;
      }
      playPreview(voice);
    },
    [playingVoiceId, playPreview],
  );

  return { playingVoiceId, playPreview, togglePreview };
}
