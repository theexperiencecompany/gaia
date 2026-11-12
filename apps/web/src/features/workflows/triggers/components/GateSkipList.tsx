"use client";

import type { GateSkipRecord } from "@shared/api/generated";
import { formatDistanceToNowStrict } from "date-fns";
import { useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import {
  GATE_NO_SKIPS_NOTE,
  GATE_SKIPS_LABEL,
  gateSkipReason,
} from "../../constants/gates";

/** The events the rule kept from running the job, newest first; one opens to say why. */
export function GateSkipList({ skips }: { skips: GateSkipRecord[] }) {
  const [openKey, setOpenKey] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs font-medium text-zinc-500">{GATE_SKIPS_LABEL}</p>
      {skips.length === 0 ? (
        <p className="text-xs text-zinc-500">{GATE_NO_SKIPS_NOTE}</p>
      ) : (
        <ul className="-mx-2 flex flex-col">
          {[...skips].reverse().map((skip) => {
            const key = `${skip.at}:${skip.event}`;
            const isOpen = openKey === key;
            return (
              <li key={key}>
                <GaiaButton
                  variant="ghost"
                  size="sm"
                  onPress={() => setOpenKey(isOpen ? null : key)}
                  aria-expanded={isOpen}
                  className="flex h-auto w-full min-w-0 flex-col items-start gap-0.5 py-1.5 text-left"
                >
                  <span className="flex w-full min-w-0 items-baseline text-xs">
                    <span className="truncate text-zinc-300" title={skip.event}>
                      {skip.event}
                    </span>
                    <time
                      dateTime={skip.at}
                      className="shrink-0 whitespace-pre tabular-nums text-zinc-500"
                    >
                      {" · "}
                      {formatDistanceToNowStrict(new Date(skip.at), {
                        addSuffix: true,
                      })}
                    </time>
                  </span>
                  {isOpen && (
                    <span className="text-xs text-zinc-500">
                      {gateSkipReason(skip.certainty)}
                    </span>
                  )}
                </GaiaButton>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
