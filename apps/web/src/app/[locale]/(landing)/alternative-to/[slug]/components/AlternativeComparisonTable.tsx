import ComparisonTable from "@/components/seo/ComparisonTable";
import type { AlternativeData } from "@/features/alternatives/data/alternativesData";

interface AlternativeComparisonTableProps {
  readonly t: (key: string, params?: Record<string, string>) => string;
  readonly data: AlternativeData;
}

export function AlternativeComparisonTable({
  t,
  data,
}: AlternativeComparisonTableProps) {
  if (!data.comparisonRows || data.comparisonRows.length === 0) return null;

  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        {t("alternatives.feature_comparison", { name: data.name })}
      </h2>
      <ComparisonTable
        ariaLabel={`GAIA vs ${data.name} feature comparison`}
        columns={[
          {
            key: "feature",
            label: t("alternatives.feature_column"),
            headerClassName: "text-zinc-500",
            cellClassName: "font-medium text-zinc-300",
          },
          {
            key: "gaia",
            label: t("alternatives.gaia_column"),
            headerClassName: "text-primary",
            cellClassName: "text-emerald-400",
          },
          {
            key: "competitor",
            label: data.name,
            headerClassName: "text-zinc-400",
            cellClassName: "text-zinc-400",
          },
        ]}
        rows={data.comparisonRows}
      />
    </section>
  );
}
