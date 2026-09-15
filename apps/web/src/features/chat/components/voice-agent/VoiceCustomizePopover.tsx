"use client";

import { Button, Popover, PopoverContent, PopoverTrigger } from "@heroui/react";
import { EditIcon } from "@icons";
import { useLocalParticipant } from "@livekit/components-react";
import { useCallback } from "react";

import { VoiceTable } from "@/features/settings/components/VoiceTable";

/**
 * In-session voice picker: a "Customise voice" button opens a popover with
 * a minimal settings voice table (name + gender icon + country only).
 *
 * Selecting persists AND re-points the live agent — patches the local
 * participant's `voiceId` metadata, which the worker already listens for
 * (tts.update_options), so it takes effect next utterance with no restart.
 */
export function VoiceCustomizePopover() {
  const { localParticipant } = useLocalParticipant();

  const applyLiveVoice = useCallback(
    (voiceId: string) => {
      if (!localParticipant) return;
      // Merge into existing metadata so agentToken / conversationId /
      // backendUrl survive the update — setMetadata replaces the whole blob.
      let meta: Record<string, unknown> = {};
      try {
        meta = localParticipant.metadata
          ? JSON.parse(localParticipant.metadata)
          : {};
      } catch {
        meta = {};
      }
      meta.voiceId = voiceId;
      localParticipant.setMetadata(JSON.stringify(meta)).catch(() => {
        // Best-effort: the choice is already persisted server-side, so a
        // failed live update just defers the swap to the next session.
      });
    },
    [localParticipant],
  );

  return (
    <Popover placement="top-end" offset={12}>
      <PopoverTrigger>
        <Button
          variant="flat"
          radius="full"
          startContent={<EditIcon className="h-4 w-4" />}
          className="bg-zinc-900/80 text-zinc-200 shadow-lg backdrop-blur-md hover:bg-zinc-800"
        >
          Customise voice
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[30rem] max-w-[calc(100vw-2rem)] p-2">
        <VoiceTable
          aria-label="Choose a voice"
          showLanguage={false}
          showPreview={false}
          inlineGender
          wrapText
          onSelect={applyLiveVoice}
          classNames={{
            base: "max-h-[60vh] overflow-y-auto overflow-x-hidden",
            wrapper: "p-0 shadow-none bg-transparent",
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
