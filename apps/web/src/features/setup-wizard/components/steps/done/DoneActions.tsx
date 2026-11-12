"use client";

import { ArrowRight02Icon } from "@icons";
import * as m from "motion/react-m";
import { LinkButton } from "@/components/shared/LinkButton";
import { PROVIDERS_SETTINGS_PATH } from "@/features/settings/components/providers/providerRows";
import { CARD_TRANSITION, CARD_VARIANTS } from "./doneMotion";

interface DoneActionsProps {
  hasLlm: boolean;
}

export function DoneActions({ hasLlm }: DoneActionsProps) {
  return (
    <m.div variants={CARD_VARIANTS} transition={CARD_TRANSITION}>
      {hasLlm ? (
        <LinkButton
          href="/c"
          variant="primary"
          fullWidth
          size="lg"
          className="font-medium"
        >
          Start chatting
          <ArrowRight02Icon size={18} />
        </LinkButton>
      ) : (
        <div className="flex flex-col gap-2">
          <LinkButton
            href={PROVIDERS_SETTINGS_PATH}
            variant="primary"
            fullWidth
            size="lg"
            className="font-medium"
          >
            Go to Providers &amp; Tools
            <ArrowRight02Icon size={18} />
          </LinkButton>
          <LinkButton
            href="/c"
            variant="ghost"
            fullWidth
            size="sm"
            tone="muted"
          >
            Continue to chat anyway
          </LinkButton>
        </div>
      )}
    </m.div>
  );
}
