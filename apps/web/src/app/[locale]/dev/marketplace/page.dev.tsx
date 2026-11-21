"use client";

import { Search01Icon } from "@icons";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { CatalogLayout } from "../explore/CatalogLayout";
import { EmptyState } from "../explore/ExploreStates";
import { FilterSelect, SearchField } from "../explore/FilterFields";
import { AppShelf } from "./AppShelf";
import { APPS, categoryLabel } from "./appModel";
import { useMarketplace } from "./useMarketplace";

/**
 * The apps GAIA can work in. GAIA's own sign in with one click; the community's
 * are MCP servers people published. Each app's page lists the templates that use it.
 */
export default function MarketplacePage() {
  const market = useMarketplace(APPS);
  return (
    <CatalogLayout
      title="Marketplace"
      description="Apps GAIA can work in. Connect one, then ask GAIA to read, write and act there."
      filters={
        <div className="flex gap-2">
          <SearchField
            value={market.query}
            onChange={market.setQuery}
            placeholder="Search apps"
            className="flex-1"
          />
          <FilterSelect
            label="Category"
            anyLabel="Any category"
            options={market.categories.map((id) => ({
              id,
              label: categoryLabel(id),
            }))}
            value={market.category}
            onChange={market.setCategory}
            className="w-36 shrink-0 sm:w-44"
          />
        </div>
      }
    >
      {market.isEmpty ? (
        <EmptyState
          Icon={Search01Icon}
          title="No apps match"
          detail="Try the app's name, or what you want it for."
          action={
            <GaiaButton
              size="sm"
              variant="default-soft"
              onPress={market.reset}
              className="h-9"
            >
              Clear filters
            </GaiaButton>
          }
        />
      ) : (
        <div className="space-y-11">
          <AppShelf
            id="gaia"
            title="Built by GAIA"
            description="Sign in once and GAIA can use it."
            apps={market.gaia}
          />
          <AppShelf
            id="community"
            title="From the community"
            description="MCP servers people have published. Some ask for a key when you add them."
            apps={market.community}
          />
        </div>
      )}
    </CatalogLayout>
  );
}
