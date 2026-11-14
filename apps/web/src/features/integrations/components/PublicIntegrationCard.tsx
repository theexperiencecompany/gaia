"use client";

import { Skeleton } from "@heroui/skeleton";
import { Tooltip } from "@heroui/tooltip";
import {
  CheckmarkBadge01Icon,
  DateTimeIcon,
  GitForkIcon,
  UserCircle02Icon,
} from "@icons";
import { formatDistanceToNow } from "date-fns";
import Image from "next/image";
import Link from "next/link";
import { isPrivateBlobUrl } from "@/lib/privateBlob";

import type { CommunityIntegration } from "../types";
import { IntegrationIcon } from "./IntegrationIcon";

function formatCloneCount(count: number): string {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`;
  }
  return count.toString();
}

function getCategoryLabel(category: string): string {
  return category.charAt(0).toUpperCase() + category.slice(1).toLowerCase();
}

interface PublicIntegrationCardProps {
  integration: CommunityIntegration;
}

export const PublicIntegrationCard: React.FC<PublicIntegrationCardProps> = ({
  integration,
}) => {
  return (
    <Link href={`/marketplace/${integration.slug}`}>
      <div className="group relative flex h-full min-h-fit w-full flex-col gap-3 rounded-3xl bg-zinc-800 p-4 outline-1 outline-zinc-800/70 transition-colors select-none cursor-pointer hover:bg-zinc-700/50">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 aspect-square shrink-0 items-center justify-center rounded-xl p-0">
            <IntegrationIcon
              integrationId={integration.integrationId}
              iconUrl={integration.iconUrl}
              size={28}
            />
          </div>

          {/* Title + Category */}
          <div className="flex flex-1 flex-col min-w-0">
            <h3 className="text-base font-medium text-zinc-100 truncate">
              {integration.name}
            </h3>
            <span className="text-xs text-zinc-500">
              {getCategoryLabel(integration.category)}
            </span>
          </div>
        </div>

        <p className="line-clamp-2 text-sm text-zinc-400 leading-relaxed">
          {integration.description}
        </p>

        <div className="mt-auto flex items-center justify-between pt-1">
          {integration.source === "platform" ? (
            <Tooltip
              content="Built and maintained by the GAIA team"
              size="sm"
              placement="top"
            >
              <div className="flex items-center gap-1.5">
                <div className="flex h-7 w-7 items-center justify-center overflow-hidden rounded-full bg-zinc-800 p-0.5">
                  <Image
                    src="/brand/gaia_logo.svg"
                    alt="GAIA"
                    width={100}
                    height={100}
                    className="object-contain"
                  />
                </div>
                <span className="truncate text-xs text-zinc-400">
                  GAIA Team
                </span>
                <CheckmarkBadge01Icon
                  width={15}
                  height={15}
                  className="shrink-0 text-primary"
                />
              </div>
            </Tooltip>
          ) : (
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 items-center justify-center rounded-full overflow-hidden p-0">
                {integration.creator?.picture ? (
                  <Image
                    src={integration.creator.picture}
                    alt={integration.creator.name ?? "Creator"}
                    width={100}
                    height={100}
                    unoptimized={isPrivateBlobUrl(integration.creator.picture)}
                    className="rounded-full object-cover"
                  />
                ) : (
                  <UserCircle02Icon className="text-zinc-500" />
                )}
              </div>
              <span className="text-xs text-zinc-500 truncate max-w-40">
                {integration.creator?.name ?? "Community"}
              </span>
            </div>
          )}

          {/* Stats */}
          <div className="flex items-center gap-4 text-xs text-zinc-500">
            {integration.source !== "platform" && (
              <div className="flex items-center gap-1">
                <GitForkIcon width={18} height={18} />
                <span>{formatCloneCount(integration.cloneCount)}</span>
              </div>
            )}
            {integration.publishedAt && (
              <div className="flex items-center gap-1">
                <DateTimeIcon width={18} height={18} />
                <span>
                  {formatDistanceToNow(new Date(integration.publishedAt), {
                    addSuffix: false,
                  })}{" "}
                  ago
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </Link>
  );
};

// Skeleton component for loading state
const PublicIntegrationCardSkeleton: React.FC = () => {
  return (
    <div className="relative flex h-full min-h-fit w-full flex-col gap-3 rounded-3xl bg-zinc-800 p-4 outline-1 outline-zinc-800/70">
      <div className="flex items-start gap-3">
        <Skeleton className="h-10 w-10 shrink-0 rounded-xl" />
        <div className="flex flex-1 flex-col gap-2 min-w-0">
          <Skeleton className="h-5 w-3/4 rounded-lg" />
          <Skeleton className="h-3 w-1/3 rounded-lg" />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-full rounded-lg" />
        <Skeleton className="h-4 w-4/5 rounded-lg" />
      </div>

      <div className="mt-auto flex items-center justify-between pt-1">
        <div className="flex items-center gap-2">
          <Skeleton className="h-6 w-6 rounded-full" />
          <Skeleton className="h-3 w-20 rounded-lg" />
        </div>
        <div className="flex items-center gap-4">
          <Skeleton className="h-3 w-12 rounded-lg" />
          <Skeleton className="h-3 w-16 rounded-lg" />
        </div>
      </div>
    </div>
  );
};

// Grid of skeleton cards for loading state
export const PublicIntegrationCardSkeletonGrid: React.FC<{
  count?: number;
}> = ({ count = 6 }) => {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: skeleton placeholders
        <PublicIntegrationCardSkeleton key={i} />
      ))}
    </>
  );
};
