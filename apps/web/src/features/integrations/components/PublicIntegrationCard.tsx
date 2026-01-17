"use client";

import { formatDistanceToNow } from "date-fns";
import Image from "next/image";
import Link from "next/link";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  DateTimeIcon,
  Download01Icon,
  GitForkIcon,
  PackageOpenIcon,
  UserCircle02Icon,
} from "@/icons";

import type { CommunityIntegration } from "../types";

interface PublicIntegrationCardProps {
  integration: CommunityIntegration;
}

export const PublicIntegrationCard: React.FC<PublicIntegrationCardProps> = ({
  integration,
}) => {
  const formatCloneCount = (count: number): string => {
    if (count >= 1000) {
      return `${(count / 1000).toFixed(1)}k`;
    }
    return count.toString();
  };

  const getCategoryLabel = (category: string): string => {
    return category.charAt(0).toUpperCase() + category.slice(1).toLowerCase();
  };

  return (
    <Link href={`/marketplace/${integration.slug}`}>
      <div className="group relative flex h-full min-h-fit w-full flex-col gap-3 rounded-3xl bg-zinc-800 p-4 outline-1 outline-zinc-800/70 transition-all select-none cursor-pointer hover:bg-zinc-700/50">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 aspect-square shrink-0 items-center justify-center rounded-xl p-0">
            {getToolCategoryIcon(
              integration.integrationId,
              { size: 100, width: 28, height: 28, showBackground: false },
              integration.iconUrl || undefined
            ) || (
              <div className="flex h-9 w-9 aspect-square items-center justify-center rounded-xl bg-zinc-700 text-sm font-medium text-zinc-300">
                <PackageOpenIcon />
              </div>
            )}
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
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-full overflow-hidden p-0">
              {integration.creator?.picture ? (
                <Image
                  src={integration.creator.picture}
                  alt={integration.creator.name ?? "Creator"}
                  width={100}
                  height={100}
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

          {/* Stats */}
          <div className="flex items-center gap-4 text-xs text-zinc-500">
            <div className="flex items-center gap-1">
              <GitForkIcon width={18} height={18} />
              <span>{formatCloneCount(integration.cloneCount)}</span>
            </div>
            <div className="flex items-center gap-1">
              <DateTimeIcon width={18} height={18} />
              <span>
                {formatDistanceToNow(new Date(integration.publishedAt), {
                  addSuffix: false,
                })}{" "}
                ago
              </span>
            </div>
          </div>
        </div>
      </div>
    </Link>
  );
};
