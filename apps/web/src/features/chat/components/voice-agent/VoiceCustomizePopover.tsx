"use client";

import { Button, Popover, PopoverContent, PopoverTrigger } from "@heroui/react";
import { PencilEdit02Icon } from "@icons";

import { VoiceTable } from "@/features/settings/components/VoiceTable";

/**
 * In-session voice picker. A bottom-right "Customise voice" button opens a
 * popover with a minimal version of the settings voice table — name, gender
 * and country only (no language column, no preview button), and selecting
 * does not auto-play a sample so it never clashes with the live agent audio.
 *
 * Selecting persists the choice; the live worker reads it from participant
 * metadata at the next session start.
 */
export function VoiceCustomizePopover() {
  return (
    <Popover placement="top-end" offset={12}>
      <PopoverTrigger>
        <Button
          variant="flat"
          radius="full"
          startContent={<PencilEdit02Icon className="h-4 w-4" />}
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
          previewOnSelect={false}
          classNames={{
            base: "max-h-[60vh] overflow-auto",
            wrapper: "p-0 shadow-none bg-transparent",
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
