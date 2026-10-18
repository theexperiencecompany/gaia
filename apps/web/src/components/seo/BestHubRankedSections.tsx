import Link from "next/link";
import type { RankedPick } from "./bestAssistantHubData";

interface RankedPickCardProps {
  readonly pick: RankedPick;
  readonly rank: number;
  readonly totalCount: number;
}

function RankedPickCard({ pick, rank, totalCount }: RankedPickCardProps) {
  return (
    <section
      id={`pick-${pick.data.slug}`}
      className="scroll-mt-32 rounded-3xl bg-zinc-800 p-8"
    >
      <p className="mb-1 text-sm text-zinc-500">
        #{rank} of {totalCount}
      </p>
      <h3 className="mb-1 text-2xl font-semibold text-white">
        {pick.data.name}
      </h3>
      <p className="mb-4 text-sm text-zinc-500">{pick.data.tagline}</p>
      <p className="mb-4 leading-relaxed text-zinc-300">
        {pick.data.description}
      </p>
      <p className="mb-6 leading-relaxed text-zinc-400">{pick.data.verdict}</p>
      <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <Link
          href={pick.compareHref}
          className="text-zinc-300 underline underline-offset-2 hover:text-white"
        >
          GAIA vs {pick.data.name}: full comparison
        </Link>
        {pick.alternativeHref && (
          <Link
            href={pick.alternativeHref}
            className="text-zinc-300 underline underline-offset-2 hover:text-white"
          >
            Best {pick.data.name} alternative guide
          </Link>
        )}
      </div>
    </section>
  );
}

export function BestHubRunnersUp({
  ranked,
}: {
  readonly ranked: readonly RankedPick[];
}) {
  const totalCount = ranked.length + 1;

  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        The {ranked.length} runners-up, in order
      </h2>
      <ol className="mb-10 space-y-2 text-zinc-400">
        {ranked.map((pick, index) => (
          <li key={pick.data.slug}>
            <span className="mr-2 text-zinc-500">{index + 2}.</span>
            <a
              href={`#pick-${pick.data.slug}`}
              className="underline underline-offset-2 hover:text-zinc-200"
            >
              {pick.data.name}
            </a>
          </li>
        ))}
      </ol>

      <div className="space-y-10">
        {ranked.map((pick, index) => (
          <RankedPickCard
            key={pick.data.slug}
            pick={pick}
            rank={index + 2}
            totalCount={totalCount}
          />
        ))}
      </div>
    </section>
  );
}
