import type { ReactNode } from "react";

/** The page both catalogues share: Explore and the marketplace read as one place in two halves. */
export function CatalogLayout({
  title,
  description,
  filters,
  children,
}: {
  title: string;
  description: string;
  filters: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="dark min-h-dvh w-full bg-primary-bg text-zinc-100 selection:bg-[#00364b] selection:text-accent">
      <main className="mx-auto w-full max-w-[46rem] px-5 pb-32 pt-16">
        <header className="px-2">
          <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em] text-white">
            {title}
          </h1>
          <p className="mt-1.5 text-[15px] leading-6 text-zinc-400">
            {description}
          </p>
        </header>
        <div className="mt-8 space-y-3">{filters}</div>
        <div className="mt-8">{children}</div>
      </main>
    </div>
  );
}
