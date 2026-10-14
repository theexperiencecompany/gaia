"use client";

import { Tick02Icon } from "@icons";
import * as m from "motion/react-m";
import nextDynamic from "next/dynamic";
import type { ReactNode } from "react";
import type { CatalogProvider } from "@/features/settings/utils/providerCatalog";
import { CARD_TRANSITION, CARD_VARIANTS } from "./doneMotion";

const ConnectedAppsCount = nextDynamic(() => import("../ConnectedAppsCount"), {
  ssr: false,
});

interface SetupSummaryCardProps {
  connectedLlmCards: CatalogProvider[];
  /** The search provider's label when configured, else null. */
  searchLabel: string | null;
  connectedTools: CatalogProvider[];
  hasAdminAccount: boolean;
}

function joinLabels(cards: CatalogProvider[]): string {
  return cards.map((card) => card.label).join(", ");
}

export function SetupSummaryCard({
  connectedLlmCards,
  searchLabel,
  connectedTools,
  hasAdminAccount,
}: SetupSummaryCardProps) {
  return (
    <m.div
      variants={CARD_VARIANTS}
      transition={CARD_TRANSITION}
      className="w-full rounded-2xl bg-zinc-800 p-4"
    >
      <p className="mb-3 text-sm font-semibold text-zinc-100">
        Your setup so far
      </p>
      <div className="space-y-2">
        <SummaryRow
          label="AI provider"
          value={
            connectedLlmCards.length > 0
              ? joinLabels(connectedLlmCards)
              : "Not set up"
          }
          done={connectedLlmCards.length > 0}
        />
        <SummaryRow
          label="Web search"
          value={searchLabel ?? "Skipped"}
          done={searchLabel !== null}
        />
        <SummaryRow
          label="Tool keys"
          value={
            connectedTools.length > 0 ? joinLabels(connectedTools) : "None yet"
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
          value={hasAdminAccount ? "Active" : "Pending"}
          done={hasAdminAccount}
        />
      </div>
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
        {done === true && (
          <Tick02Icon height={14} className="text-emerald-400" />
        )}
        {value}
      </span>
    </div>
  );
}
