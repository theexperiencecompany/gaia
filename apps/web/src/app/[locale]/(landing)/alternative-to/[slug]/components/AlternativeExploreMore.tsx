import Link from "next/link";

interface AlternativeExploreMoreProps {
  readonly t: (key: string) => string;
}

export function AlternativeExploreMore({ t }: AlternativeExploreMoreProps) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        {t("common.explore_more")}
      </h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Link
          href="/compare"
          className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
        >
          <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
            {t("alternatives.gaia_vs_competitors")}
          </h3>
          <p className="text-sm leading-relaxed text-zinc-400">
            {t("alternatives.gaia_vs_competitors_desc")}
          </p>
        </Link>
        <Link
          href="/for"
          className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
        >
          <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
            {t("alternatives.gaia_for_role")}
          </h3>
          <p className="text-sm leading-relaxed text-zinc-400">
            {t("alternatives.gaia_for_role_desc")}
          </p>
        </Link>
      </div>
    </section>
  );
}
