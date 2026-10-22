"use client";

import { Button } from "@heroui/button";
import { Alert01Icon } from "@icons";
import * as m from "motion/react-m";
import Link from "next/link";
import { PROVIDERS_SETTINGS_PATH } from "@/features/settings/components/providers/providerRows";
import { CARD_TRANSITION, CARD_VARIANTS } from "./doneMotion";

export function SkippedProviderCard() {
  return (
    <m.div
      variants={CARD_VARIANTS}
      transition={CARD_TRANSITION}
      className="w-full rounded-2xl bg-zinc-800 p-6"
    >
      <div className="flex gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-amber-400/10">
          <Alert01Icon size={18} className="text-amber-400" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-zinc-100">
            You skipped provider setup
          </p>
          <p className="mt-1 text-sm leading-relaxed text-zinc-400">
            Chat requires a provider to work. Add a key in{" "}
            <span className="font-medium text-zinc-300">
              Settings, under Providers &amp; Tools
            </span>{" "}
            to start chatting — one key is all it takes.
          </p>
          <Button
            as={Link}
            href={PROVIDERS_SETTINGS_PATH}
            size="sm"
            variant="flat"
            className="mt-3"
          >
            Go to Settings
          </Button>
        </div>
      </div>
    </m.div>
  );
}
