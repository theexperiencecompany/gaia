"use client";

import { Renderer } from "@openuidev/react-lang";
import { normalizeOpenUICode } from "@shared/utils";
import { type JSX, useMemo, useState } from "react";
import ErrorBoundary from "@/components/shared/ErrorBoundary";
import { OPENUI_EXAMPLES } from "@/config/openui/examples";
import { genericLibrary } from "@/config/openui/genericLibrary";

/**
 * OpenUI playground (dev only).
 *
 * Renders example OpenUI Lang programs through the merged `@openuidev/react-ui`
 * library under the GAIA theme, plus a live editor for pasting DSL. Use this to
 * eyeball component theming and composition without a full chat round-trip.
 */
export default function OpenUIPlaygroundPage(): JSX.Element {
  const [code, setCode] = useState(OPENUI_EXAMPLES[0].code);

  const normalized = useMemo(
    () => normalizeOpenUICode(code, genericLibrary),
    [code],
  );

  return (
    <div className="h-full overflow-hidden bg-primary-bg">
      <div className="mx-auto flex h-full w-full max-w-[1600px] flex-col gap-4 px-6 py-6">
        <header className="shrink-0">
          <h1 className="text-2xl font-semibold text-zinc-100">
            OpenUI Playground
          </h1>
          <p className="mt-1 text-sm text-zinc-400">
            Live-render OpenUI Lang through the merged react-ui library (themed
            to GAIA). Pick an example or paste your own DSL.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {OPENUI_EXAMPLES.map((ex) => (
              <button
                key={ex.id}
                type="button"
                onClick={() => setCode(ex.code)}
                className="rounded-full bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 transition-colors hover:bg-zinc-700"
              >
                {ex.name}
              </button>
            ))}
          </div>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            spellCheck={false}
            className="h-full min-h-0 w-full resize-none overflow-auto rounded-2xl bg-zinc-900 p-4 font-mono text-xs leading-relaxed text-zinc-300 outline-none ring-1 ring-zinc-800 focus:ring-zinc-700"
          />
          <div className="h-full min-h-0 overflow-auto rounded-2xl bg-zinc-950 p-4 ring-1 ring-zinc-800">
            <ErrorBoundary>
              <Renderer
                response={normalized}
                library={genericLibrary}
                isStreaming={false}
              />
            </ErrorBoundary>
          </div>
        </div>
      </div>
    </div>
  );
}
