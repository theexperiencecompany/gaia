"use client";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { appName } from "../marketplace/appModel";
import TaskSection from "../tasks/TaskSection";
import { TemplateRow } from "./TemplateRow";
import { ALL, type ExploreState } from "./useExplore";

/** How many rows a category shows on the All view before "Show all". */
const SHELF_ROWS = 5;

/** What the narrowed list is called: the category, the app, or both. */
function resultTitle({ filters }: ExploreState): string {
  const app = filters.app === ALL ? "" : appName(filters.app);
  if (filters.category === ALL) return app ? `With ${app}` : "Results";
  return app ? `${filters.category} with ${app}` : filters.category;
}

/**
 * The list under the filters. Untouched, it is one short shelf per category, so
 * the range shows at a glance; any filter turns it into one flat list.
 */
export function ExploreShelves({ explore }: { explore: ExploreState }) {
  if (explore.isNarrowed) {
    return (
      <TaskSection
        id="results"
        title={resultTitle(explore)}
        count={explore.results.length}
      >
        <ul>
          {explore.results.map((template) => (
            <TemplateRow key={template.data.id} template={template} />
          ))}
        </ul>
      </TaskSection>
    );
  }

  return (
    <div className="space-y-11">
      {explore.shelves.map((shelf) => (
        <TaskSection
          key={shelf.category}
          id={shelf.category}
          title={shelf.category}
          count={shelf.templates.length}
          action={
            shelf.templates.length > SHELF_ROWS && (
              <GaiaButton
                size="sm"
                variant="quiet"
                tone="faint"
                hoverTone="bright"
                inset="tight"
                onPress={() => {
                  explore.setFilters({ category: shelf.category });
                  window.scrollTo({ top: 0 });
                }}
                className="h-7 min-w-0 text-[13px] leading-[1.5]"
              >
                Show all
              </GaiaButton>
            )
          }
        >
          <ul>
            {shelf.templates.slice(0, SHELF_ROWS).map((template) => (
              <TemplateRow key={template.data.id} template={template} />
            ))}
          </ul>
        </TaskSection>
      ))}
    </div>
  );
}
