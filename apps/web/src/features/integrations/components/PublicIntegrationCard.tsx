"use client";

import { formatDistanceToNow } from "date-fns";
import Image from "next/image";
import Link from "next/link";
import { useState } from "react";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  DateTimeIcon,
  GitForkIcon,
  PackageOpenIcon,
  UserCircle02Icon,
} from "@/icons";

import type { CommunityIntegration } from "../types";

// Component to handle integration icon with fallback on error
const IntegrationIcon: React.FC<{
  integrationId: string;
  iconUrl?: string | null;
}> = ({ integrationId, iconUrl }) => {
  const [hasError, setHasError] = useState(false);

  // First, try to get the icon from toolCategoryIcon (which checks known categories)
  const categoryIcon = getToolCategoryIcon(integrationId, {
    size: 100,
    width: 28,
    height: 28,
    showBackground: false,
  });

  // If we have a category icon, use it directly
  if (categoryIcon) {
    return <>{categoryIcon}</>;
  }

  // Otherwise, try to use the iconUrl with error handling
  if (iconUrl && !hasError) {
    // Use regular img tag for SVG URLs to avoid Next.js Image optimization issues
    const isSvg = iconUrl.toLowerCase().endsWith(".svg");
    if (isSvg) {
      return (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={iconUrl}
          alt="Integration icon"
          width={28}
          height={28}
          className="aspect-square object-contain"
          onError={() => setHasError(true)}
        />
      );
    }
    return (
      <Image
        src={iconUrl}
        alt="Integration icon"
        width={28}
        height={28}
        className="aspect-square object-contain"
        onError={() => setHasError(true)}
      />
    );
  }

  // Fallback to PackageOpenIcon
  return (
    <div className="flex h-9 w-9 aspect-square items-center justify-center rounded-xl bg-zinc-700 text-sm font-medium text-zinc-300">
      <PackageOpenIcon />
    </div>
  );
};

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
    <Link href={`/marketplace/${integration.integrationId}`}>
      <div className="group relative flex h-full min-h-fit w-full flex-col gap-3 rounded-3xl bg-zinc-800 p-4 outline-1 outline-zinc-800/70 transition-all select-none cursor-pointer hover:bg-zinc-700/50">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 aspect-square shrink-0 items-center justify-center rounded-xl p-0">
            <IntegrationIcon
              integrationId={integration.integrationId}
              iconUrl={integration.iconUrl}
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
