/**
 * Wizard step 4 — summary of everything configured, marks the wizard
 * complete (POST /setup/complete {step:"wizard"}), and hands the user off
 * to chat.
 */

"use client";

import { Button } from "@heroui/button";
import { Tick02Icon } from "@icons";
import * as m from "motion/react-m";
import nextDynamic from "next/dynamic";
import Link from "next/link";
import { type ReactNode, useEffect } from "react";
import type { SetupStatus } from "@/features/settings/api/providersApi";
import { isProviderConfigured } from "@/features/settings/hooks/useSetupStatus";
import { apiService } from "@/lib/api/service";
import {
  LLM_PROVIDER_CARDS,
  MOTION_FADE_UP,
  SEARCH_PROVIDER_CARD,
  TOOL_PROVIDER_CARDS,
} from "../../constants";

const ConnectedAppsCount = nextDynamic(() => import("./ConnectedAppsCount"), {
  ssr: false,
});

interface DoneStepProps {
  status: SetupStatus;
}

function providerLabel(key: string): string {
  return (
    [...LLM_PROVIDER_CARDS, SEARCH_PROVIDER_CARD, ...TOOL_PROVIDER_CARDS].find(
      (card) => card.key === key,
    )?.label ?? key
  );
}

export function DoneStep({ status }: DoneStepProps) {
  useEffect(() => {
    apiService
      .post("setup/complete", { step: "wizard" }, { silent: true })
      .catch((err: unknown) => {
        console.error("Failed to mark setup complete:", err);
      });
  }, []);

  const connectedLlm = LLM_PROVIDER_CARDS.filter((card) =>
    isProviderConfigured(status, card.key),
  ).map((card) => card.label);

  const searchConfigured = isProviderConfigured(
    status,
    SEARCH_PROVIDER_CARD.key,
  );

  const connectedTools = TOOL_PROVIDER_CARDS.filter((card) =>
    isProviderConfigured(status, card.key),
  );

  return (
    <m.div className="flex w-full flex-col gap-3" {...MOTION_FADE_UP}>
      <div className="w-full rounded-2xl bg-zinc-800 p-4">
        <p className="mb-3 text-sm font-semibold text-zinc-100">
          Instance summary
        </p>
        <div className="space-y-2">
          <SummaryRow
            label="AI provider"
            value={
              connectedLlm.length > 0 ? connectedLlm.join(", ") : "Not set up"
            }
            done={connectedLlm.length > 0}
          />
          <SummaryRow
            label="Web search"
            value={
              searchConfigured
                ? providerLabel(SEARCH_PROVIDER_CARD.key)
                : "Skipped"
            }
            done={searchConfigured}
          />
          <SummaryRow
            label="Tool keys"
            value={
              connectedTools.length > 0
                ? connectedTools.map((card) => card.label).join(", ")
                : "None yet"
            }
            done={null}
          />
          <SummaryRow
            label="Connected accounts"
            value={<ConnectedAppsCount />}
            done={null}
          />
          <SummaryRow
            label="Admin account"
            value={status.has_admin_account ? "Active" : "Pending"}
            done={status.has_admin_account}
          />
        </div>
      </div>

      <Button
        as={Link}
        href="/c"
        color="primary"
        fullWidth
        size="lg"
        className="font-medium"
      >
        Start chatting
      </Button>
      {!searchConfigured && (
        <p className="text-center text-xs text-zinc-500">
          Skipped something? You can finish anytime from Settings → Providers.
        </p>
      )}
    </m.div>
  );
}

function SummaryRow({
  label,
  value,
  done,
}: {
  label: string;
  value: ReactNode;
  /** null = informational row without a done/pending verdict */
  done: boolean | null;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-zinc-900 p-3">
      <span className="text-sm font-medium text-zinc-200">{label}</span>
      <span className="flex items-center gap-1.5 text-xs text-zinc-400">
        {done !== null && done && (
          <Tick02Icon height={14} className="text-emerald-400" />
        )}
        {value}
      </span>
    </div>
  );
}
