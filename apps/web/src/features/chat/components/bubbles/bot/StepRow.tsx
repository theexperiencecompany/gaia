"use client";

import Image from "next/image";
import { useImageDialog } from "@/stores/uiStore";
import type { BrowserStepSnapshot } from "@/types/features/browserTaskTypes";

/** Split the runner's "name({args}); name({args})" summary into rendered calls. */
function parseActions(action: string): { name: string; args: string }[] {
  return action
    .split("; ")
    .map((part) => {
      const open = part.indexOf("(");
      if (open === -1) return { name: part.trim(), args: "" };
      return {
        name: part.slice(0, open).trim(),
        args: part.slice(open + 1, part.lastIndexOf(")")).trim(),
      };
    })
    .filter((call) => call.name.length > 0);
}

// "820ms" under a second, "6.8s" above — the same rounding a person does.
function formatStepDuration(ms: number): string {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export function StepRow({ step }: { step: BrowserStepSnapshot }) {
  const { openDialog } = useImageDialog();
  return (
    <div className="rounded-2xl bg-zinc-900 p-3">
      <div className="flex items-start gap-2.5">
        <span className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-xs font-medium text-zinc-400">
          {step.index}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium leading-snug text-zinc-100">
            {step.goal}
          </p>
          {step.url && (
            <p className="mt-0.5 truncate text-xs text-zinc-500">{step.url}</p>
          )}
          {/* What the agent actually called this step — the browser tool and the
              arguments it passed. Streamed all along but never rendered, so a
              step read as a vague intention with no evidence under it. */}
          {step.action && (
            <div className="mt-1.5 flex flex-col gap-1">
              {parseActions(step.action).map((call) => (
                <div
                  key={`${step.index}-${call.name}-${call.args}`}
                  className="flex min-w-0 items-baseline gap-1.5 rounded-lg bg-zinc-800 px-2 py-1"
                >
                  <span className="shrink-0 font-mono text-[11px] text-[#00bbff]">
                    {call.name}
                  </span>
                  {call.args && (
                    <span className="truncate font-mono text-[11px] text-zinc-400">
                      {call.args}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
        {step.elapsed_ms != null && step.elapsed_ms > 0 && (
          <span className="shrink-0 text-xs tabular-nums text-zinc-500">
            {formatStepDuration(step.elapsed_ms)}
          </span>
        )}
      </div>
      {step.screenshot && (
        <button
          type="button"
          onClick={() => openDialog(step.screenshot as string)}
          className="group mt-2.5 block w-full overflow-hidden rounded-xl transition hover:opacity-90"
          aria-label={`Enlarge step ${step.index} screenshot`}
        >
          <Image
            src={step.screenshot}
            alt={`Step ${step.index} screenshot`}
            width={1280}
            height={720}
            className="h-auto w-full transition group-hover:opacity-90"
            unoptimized
          />
        </button>
      )}
    </div>
  );
}
