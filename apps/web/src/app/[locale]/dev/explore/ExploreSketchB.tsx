"use client";

import type { ReactNode } from "react";

import TaskSection from "../tasks/TaskSection";
import { CategoryBar, CategoryRail } from "./CategoryBar";
import { TemplateTile } from "./TemplateTile";
import type { ExploreState } from "./useExplore";

/** Sketch B: a category rail beside a two-column index of tiles. */
export function ExploreSketchB({
  explore,
  search,
}: {
  explore: ExploreState;
  search: ReactNode;
}) {
  const { filters, setFilters } = explore;
  const groups = explore.isNarrowed
    ? [{ category: "Results", templates: explore.results }]
    : explore.shelves;

  return (
    <div className="dark min-h-dvh w-full bg-primary-bg text-zinc-100">
      <main className="mx-auto w-full max-w-[72rem] px-5 pb-32 pt-16">
        <header className="px-2">
          <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em] text-white">
            Explore
          </h1>
          <p className="mt-1.5 text-[15px] leading-6 text-zinc-400">
            Ready-made tasks for GAIA. Use one as it is, or change it to fit.
          </p>
        </header>
        <div className="mt-8 grid gap-8 md:grid-cols-[12rem_1fr]">
          <aside className="hidden md:block">
            <div className="sticky top-8">
              <CategoryRail
                categories={explore.categories}
                value={filters.category}
                onChange={(category) => setFilters({ category })}
              />
            </div>
          </aside>
          <div className="min-w-0 space-y-8">
            <div className="space-y-3">
              {search}
              <div className="md:hidden">
                <CategoryBar
                  categories={explore.categories}
                  value={filters.category}
                  onChange={(category) => setFilters({ category })}
                />
              </div>
            </div>
            {groups.map((group) => (
              <TaskSection
                key={group.category}
                id={group.category}
                title={group.category}
                count={group.templates.length}
              >
                <ul className="grid gap-1 sm:grid-cols-2">
                  {group.templates.map((template) => (
                    <TemplateTile key={template.data.id} template={template} />
                  ))}
                </ul>
              </TaskSection>
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}
