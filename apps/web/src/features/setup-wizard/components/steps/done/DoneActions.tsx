"use client";

import { Button } from "@heroui/react";
import { ArrowRight02Icon } from "@icons";
import * as m from "motion/react-m";
import Link from "next/link";
import type { ComponentProps } from "react";
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
          render={(props) => (
            <Link {...(props as unknown as ComponentProps<"a">)} href="/c" />
          )}
          variant="primary"
          fullWidth
          size="lg"
          className="font-medium"
        >
          Start chatting
          <ArrowRight02Icon size={18} />
        </Button>
      ) : (
        <div className="flex flex-col gap-2">
          <Button
            render={(props) => (
              <Link
                {...(props as unknown as ComponentProps<"a">)}
                href={PROVIDERS_SETTINGS_PATH}
              />
            )}
            variant="primary"
            fullWidth
            size="lg"
            className="font-medium"
          >
            Go to Providers &amp; Tools
            <ArrowRight02Icon size={18} />
          </Button>
          <Button
            render={(props) => (
              <Link {...(props as unknown as ComponentProps<"a">)} href="/c" />
            )}
            variant="ghost"
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
