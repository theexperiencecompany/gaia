import Link from "next/link";

interface AlternativeBreadcrumbProps {
  readonly t: (key: string, params?: Record<string, string>) => string;
  readonly name: string;
}

export function AlternativeBreadcrumb({ t, name }: AlternativeBreadcrumbProps) {
  return (
    <nav className="mb-8 text-sm text-zinc-500">
      <Link href="/" className="hover:text-zinc-300">
        {t("common.home")}
      </Link>
      <span className="mx-2">/</span>
      <Link href="/alternative-to" className="hover:text-zinc-300">
        {t("alternatives.breadcrumb")}
      </Link>
      <span className="mx-2">/</span>
      <span className="text-zinc-300">
        {t("alternatives.best_alternative", { name })}
      </span>
    </nav>
  );
}
