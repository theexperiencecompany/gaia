"use client";

import Link from "next/link";

interface AutomateCombo {
  readonly slug: string;
  readonly toolA: string;
  readonly toolB: string;
  readonly tagline: string;
}

/** Matching automate guides: detail -> /automate cross-links. */
export function IntegrationAutomateCombos({
  combos,
  integrationName,
}: {
  readonly combos: readonly AutomateCombo[];
  readonly integrationName: string;
}) {
  return (
    <section className="space-y-6 rounded-3xl bg-zinc-900/50 p-8 backdrop-blur-md">
      <div>
        <h2 className="mb-2 text-2xl font-medium text-foreground">
          Automate {integrationName} with other tools
        </h2>
        <p className="text-sm leading-relaxed text-zinc-400">
          Step-by-step guides for connecting {integrationName} to the tools you
          already use.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {combos.map((combo) => (
          <Link
            key={combo.slug}
            href={`/automate/${combo.slug}`}
            className="group rounded-3xl bg-zinc-800 p-4 transition-colors select-none hover:bg-zinc-700/50"
          >
            <h3 className="mb-1 text-base font-medium text-zinc-100 group-hover:text-primary">
              {combo.toolA} + {combo.toolB}
            </h3>
            <p className="line-clamp-2 text-sm leading-relaxed text-zinc-400">
              {combo.tagline}
            </p>
          </Link>
        ))}
      </div>
    </section>
  );
}
