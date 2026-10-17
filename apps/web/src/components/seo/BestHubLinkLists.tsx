import Link from "next/link";
import type { AlternativeData } from "@/features/alternatives/data/alternativesData";
import type { ComparisonData } from "@/features/comparisons/data/comparisonsData";

/** The two bottom link lists: every comparison, then every alternative guide. */
export default function BestHubLinkLists({
  comparisons,
  alternatives,
  comparisonsTitle,
  alternativesTitle,
}: {
  readonly comparisons: readonly ComparisonData[];
  readonly alternatives: readonly AlternativeData[];
  readonly comparisonsTitle: string;
  readonly alternativesTitle: string;
}) {
  return (
    <>
      <section className="mb-16">
        <h2 className="mb-4 text-3xl font-semibold text-white">
          {comparisonsTitle}
        </h2>
        <p className="mb-6 leading-relaxed text-zinc-400">
          We publish a full head-to-head for each tool below. Start from the{" "}
          <Link
            href="/compare"
            className="underline underline-offset-2 hover:text-zinc-200"
          >
            comparisons hub
          </Link>{" "}
          or jump straight in:
        </p>
        <ul className="columns-2 gap-6 text-sm leading-loose text-zinc-400 sm:columns-3">
          {comparisons.map((comparison) => (
            <li key={comparison.slug} className="break-inside-avoid">
              <Link
                href={`/compare/${comparison.slug}`}
                className="hover:text-zinc-200 hover:underline hover:underline-offset-2"
              >
                GAIA vs {comparison.name}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="mb-16">
        <h2 className="mb-4 text-3xl font-semibold text-white">
          {alternativesTitle}
        </h2>
        <p className="mb-6 leading-relaxed text-zinc-400">
          Migration-focused guides with fit scores and switch steps. Browse the{" "}
          <Link
            href="/alternative-to"
            className="underline underline-offset-2 hover:text-zinc-200"
          >
            alternatives hub
          </Link>{" "}
          or jump straight in:
        </p>
        <ul className="columns-2 gap-6 text-sm leading-loose text-zinc-400 sm:columns-3">
          {alternatives.map((alternative) => (
            <li key={alternative.slug} className="break-inside-avoid">
              <Link
                href={`/alternative-to/${alternative.slug}`}
                className="hover:text-zinc-200 hover:underline hover:underline-offset-2"
              >
                Best {alternative.name} alternative
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
