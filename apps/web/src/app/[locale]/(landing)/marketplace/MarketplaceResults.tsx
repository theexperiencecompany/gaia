"use client";

import { Pagination } from "@heroui/pagination";
import {
  PublicIntegrationCard,
  PublicIntegrationCardSkeletonGrid,
} from "@/features/integrations/components/PublicIntegrationCard";
import type { CommunityIntegration } from "@/features/integrations/types";

/** The results area: loading skeletons, empty state, or the card grid with
 * pagination over the community endpoint. */
export function MarketplaceResults({
  isLoading,
  isEmpty,
  nativeIntegrations,
  integrations,
  showNative,
  totalPages,
  currentPage,
  onPageChange,
}: {
  readonly isLoading: boolean;
  readonly isEmpty: boolean;
  readonly nativeIntegrations: readonly CommunityIntegration[];
  readonly integrations: readonly CommunityIntegration[];
  readonly showNative: boolean;
  readonly totalPages: number;
  readonly currentPage: number;
  readonly onPageChange: (page: number) => void;
}) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
        <PublicIntegrationCardSkeletonGrid count={6} />
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div className="py-20 text-center">
        <p className="text-zinc-400">No integrations found</p>
        <p className="mt-2 text-sm text-zinc-500">
          Try adjusting your search or filters
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
        {/* Native integrations are not paginated by the community endpoint,
            so show them once on the first page instead of re-pinning them
            on top of every page. */}
        {showNative &&
          nativeIntegrations.map((integration) => (
            <PublicIntegrationCard
              key={integration.integrationId}
              integration={integration}
            />
          ))}
        {integrations.map((integration) => (
          <PublicIntegrationCard
            key={integration.integrationId}
            integration={integration}
          />
        ))}
      </div>

      {/* Pagination — community only */}
      {totalPages > 1 && (
        <div className="mt-12 flex justify-center">
          <Pagination
            total={totalPages}
            page={currentPage}
            onChange={onPageChange}
            showControls
            variant="faded"
            classNames={{
              base: "cursor-pointer!",
            }}
          />
        </div>
      )}
    </>
  );
}
