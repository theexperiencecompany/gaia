"use client";

import { Search01Icon, SparklesIcon } from "@icons";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { appName } from "../marketplace/appModel";
import { AppIcon } from "../tasks/TaskParts";
import { CatalogLayout } from "./CatalogLayout";
import { CategoryBar } from "./CategoryBar";
import { ExploreShelves } from "./ExploreShelves";
import { EmptyState, LoadingRows } from "./ExploreStates";
import { FilterSelect, SearchField } from "./FilterFields";
import { atScale, TEMPLATES } from "./templateModel";
import { ALL, type ExploreState, useExplore } from "./useExplore";

function ExploreBody({
  explore,
  isLoading,
  isEmpty,
}: {
  explore: ExploreState;
  isLoading: boolean;
  isEmpty: boolean;
}) {
  if (isLoading) return <LoadingRows />;
  if (isEmpty) {
    return (
      <EmptyState
        Icon={SparklesIcon}
        title="Nothing here yet"
        detail="Templates appear here once GAIA or someone in the community publishes one."
      />
    );
  }
  if (explore.results.length === 0) {
    return (
      <EmptyState
        Icon={Search01Icon}
        title="No templates match"
        detail="Try another word, or look in every category."
        action={
          <GaiaButton
            size="sm"
            variant="default-soft"
            onPress={explore.reset}
            className="h-9"
          >
            Clear filters
          </GaiaButton>
        }
      />
    );
  }
  return <ExploreShelves explore={explore} />;
}

/** ?n=200 shows the page at catalogue scale; ?state=loading|empty shows those states. */
function Explore() {
  const params = useSearchParams();
  const state = params.get("state");
  const data =
    state === "empty"
      ? []
      : atScale(Number(params.get("n") ?? TEMPLATES.length));
  const explore = useExplore(data, {
    category: params.get("category") ?? ALL,
    app: params.get("app") ?? ALL,
  });
  const { filters, setFilters } = explore;
  const appOptions = explore.apps.map((app) => ({
    id: app,
    text: appName(app),
    icon: <AppIcon id={app} size={16} />,
  }));

  const search = (
    <div className="flex gap-2">
      <SearchField
        value={filters.query}
        onChange={(query) => setFilters({ query })}
        placeholder="Search templates"
        className="flex-1"
      />
      <FilterSelect
        label="App"
        anyLabel="Any app"
        options={appOptions}
        value={filters.app}
        onChange={(app) => setFilters({ app })}
        className="w-36 shrink-0 sm:w-44"
      />
    </div>
  );

  return (
    <CatalogLayout
      title="Explore"
      description="Ready-made tasks for GAIA. Use one as it is, or change it to fit."
      filters={
        <>
          {search}
          <CategoryBar
            categories={state === "loading" ? [] : explore.categories}
            value={filters.category}
            onChange={(category) => setFilters({ category })}
          />
        </>
      }
    >
      <ExploreBody
        explore={explore}
        isLoading={state === "loading"}
        isEmpty={data.length === 0}
      />
    </CatalogLayout>
  );
}

export default function ExplorePage() {
  return (
    <Suspense>
      <Explore />
    </Suspense>
  );
}
