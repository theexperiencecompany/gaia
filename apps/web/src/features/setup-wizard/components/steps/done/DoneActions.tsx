"use client";

import { Button } from "@heroui/button";
import { ArrowRight02Icon } from "@icons";
import * as m from "motion/react-m";
import Link from "next/link";
import { PROVIDERS_SETTINGS_PATH } from "@/features/settings/components/providers/providerRows";
import { CARD_TRANSITION, CARD_VARIANTS } from "./doneMotion";

interface DoneActionsProps {
  hasLlm: boolean;
}

export function DoneActions({ hasLlm }: DoneActionsProps) {
  return (
    <m.div variants={CARD_VARIANTS} transition={CARD_TRANSITION}>
      {hasLlm ? (
        <Button
          as={Link}
          href="/c"
          color="primary"
          fullWidth
          size="lg"
          className="font-medium"
          endContent={<ArrowRight02Icon size={18} />}
        >
          Start chatting
        </Button>
      ) : (
        <div className="flex flex-col gap-2">
          <Button
            as={Link}
            href={PROVIDERS_SETTINGS_PATH}
            color="primary"
            fullWidth
            size="lg"
            className="font-medium"
            endContent={<ArrowRight02Icon size={18} />}
          >
            Go to Providers &amp; Tools
          </Button>
          <Button
            as={Link}
            href="/c"
            variant="light"
            fullWidth
            size="sm"
            className="text-zinc-400"
          >
            Continue to chat anyway
          </Button>
        </div>
      )}
    </m.div>
  );
}
