"use client";

import { Button } from "@heroui/button";
import { KeyIcon } from "@icons";
import Link from "next/link";
import {
  COMPOSIO_APP_COUNT,
  COMPOSIO_SETUP_PATH,
} from "@/features/settings/api/composioSetupApi";

/** The catalog's state before this instance has a Composio key: what the key unlocks and where to add it. */
export function ComposioKeyMissing({ onNavigate }: { onNavigate: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl bg-zinc-900 px-6 py-12 text-center">
      <span className="flex size-10 items-center justify-center rounded-xl bg-primary/20 text-primary">
        <KeyIcon className="size-5" />
      </span>
      <div>
        <p className="text-sm font-medium text-zinc-100">
          Add a Composio key to browse {COMPOSIO_APP_COUNT} apps
        </p>
        <p className="mt-1 text-sm text-zinc-400">
          The catalog comes from your own Composio project, so it opens once its
          key is saved.
        </p>
      </div>
      <Button
        as={Link}
        href={COMPOSIO_SETUP_PATH}
        color="primary"
        onPress={onNavigate}
      >
        Add Composio key
      </Button>
    </div>
  );
}
