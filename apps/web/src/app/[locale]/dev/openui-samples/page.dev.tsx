"use client";

import { Renderer } from "@openuidev/react-lang";
import { normalizeOpenUICode, OPENUI_SAMPLES } from "@shared/utils";
import type { JSX } from "react";
import ErrorBoundary from "@/components/shared/ErrorBoundary";
import { genericLibrary } from "@/config/openui/genericLibrary";

function SampleCard({
  name,
  code,
}: {
  name: string;
  code: string;
}): JSX.Element {
  const normalized = normalizeOpenUICode(code, genericLibrary);
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
          {name}
        </h2>
      </div>
      <ErrorBoundary>
        <Renderer
          response={normalized}
          library={genericLibrary}
          isStreaming={false}
        />
      </ErrorBoundary>
      <details className="text-xs text-zinc-600">
        <summary className="cursor-pointer text-zinc-500 hover:text-zinc-400">
          Source
        </summary>
        <pre className="mt-2 overflow-x-auto rounded-lg bg-zinc-900 p-3 font-mono text-[11px] leading-relaxed text-zinc-400">
          {code}
        </pre>
      </details>
    </section>
  );
}

export default function OpenUISamplesPage(): JSX.Element {
  const groups = OPENUI_SAMPLES.reduce<Record<string, typeof OPENUI_SAMPLES>>(
    (acc, s) => {
      const bucket = acc[s.group] ?? [];
      bucket.push(s);
      acc[s.group] = bucket;
      return acc;
    },
    {},
  );

  return (
    <div className="h-full overflow-y-auto bg-primary-bg">
      <div className="mx-auto w-full max-w-3xl px-6 py-10">
        <header className="mb-10">
          <h1 className="text-3xl font-semibold text-zinc-100">
            OpenUI Component Gallery
          </h1>
          <p className="mt-2 text-sm text-zinc-400">
            All 35 OpenUI components rendered from shared samples in{" "}
            <code className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-xs text-zinc-300">
              @gaia/shared/utils
            </code>
            . Open the mobile gallery at{" "}
            <code className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-xs text-zinc-300">
              (app)/openui-demo
            </code>{" "}
            side-by-side to spot visual drift.
          </p>
        </header>

        {Object.entries(groups).map(([group, samples]) => (
          <div key={group} className="mb-12">
            <h3 className="mb-6 text-lg font-semibold text-zinc-200">
              {group}
            </h3>
            <div className="flex flex-col gap-10">
              {samples.map((s) => (
                <SampleCard key={s.name} name={s.name} code={s.code} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
