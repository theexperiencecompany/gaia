import Link from "next/link";

interface LinkedGuide {
  readonly slug: string;
  readonly name: string;
}

export function BestHubComparisonLinks({
  title,
  comparisons,
}: {
  readonly title: string;
  readonly comparisons: readonly LinkedGuide[];
}) {
  return (
    <section className="mb-16">
      <h2 className="mb-4 text-3xl font-semibold text-white">{title}</h2>
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
  );
}

export function BestHubAlternativeLinks({
  title,
  alternatives,
}: {
  readonly title: string;
  readonly alternatives: readonly LinkedGuide[];
}) {
  return (
    <section className="mb-16">
      <h2 className="mb-4 text-3xl font-semibold text-white">{title}</h2>
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
              {alternative.name} alternatives
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
