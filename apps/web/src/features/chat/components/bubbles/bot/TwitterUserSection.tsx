"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@radix-ui/react-avatar";
import { format, parseISO } from "date-fns";
import {
  Calendar01Icon,
  CheckmarkBadge02Icon,
  LinkIcon,
  MapsIcon,
} from "@/icons";
import type { TwitterUserData } from "@/types/features/twitterTypes";

/**
 * Twitter User Card - Displays a user profile with metrics.
 * Styled to closely match the real Twitter/X profile card.
 */
function TwitterUserCard({
  user,
  onFollow,
}: {
  user: TwitterUserData;
  onFollow?: (userId: string) => void;
}) {
  const metrics = user.public_metrics || {};

  const formatNumber = (num: number | undefined) => {
    if (!num) return "0";
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  const formatJoinDate = (dateStr?: string) => {
    if (!dateStr) return "";
    try {
      return format(parseISO(dateStr), "MMMM yyyy");
    } catch {
      return dateStr;
    }
  };

  const handleOpenProfile = () => {
    window.open(`https://twitter.com/${user.username}`, "_blank");
  };

  return (
    <div
      className="group relative flex w-full flex-col gap-3 rounded-xl border border-default-200 bg-content1/50 p-4 backdrop-blur-sm transition-all hover:border-default-300 hover:bg-content1/70 cursor-pointer"
      onClick={handleOpenProfile}
    >
      {/* Header Row */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <Avatar className="h-12 w-12 shrink-0 rounded-full overflow-hidden">
            <AvatarImage
              src={user.profile_image_url}
              alt={user.name}
              className="h-full w-full object-cover"
            />
            <AvatarFallback className="flex h-full w-full items-center justify-center bg-primary/10 text-primary text-lg font-semibold">
              {user.name?.[0]?.toUpperCase() || "?"}
            </AvatarFallback>
          </Avatar>

          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-1">
              <span className="font-bold text-foreground text-sm truncate">
                {user.name}
              </span>
              {user.verified && (
                <CheckmarkBadge02Icon className="h-4 w-4 text-[#1d9bf0] shrink-0" />
              )}
            </div>
            <span className="text-xs text-default-500">@{user.username}</span>
          </div>
        </div>

        {onFollow && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onFollow(user.id);
            }}
            type="button"
            className="rounded-full bg-foreground text-background px-4 py-1.5 text-sm font-semibold hover:bg-foreground/90 transition-colors"
          >
            Follow
          </button>
        )}
      </div>

      {/* Bio */}
      {user.description && (
        <p className="text-sm text-foreground leading-relaxed">
          {user.description}
        </p>
      )}

      {/* Meta Info */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-default-500">
        {user.location && (
          <div className="flex items-center gap-1">
            <MapsIcon className="h-3.5 w-3.5" />
            <span>{user.location}</span>
          </div>
        )}
        {user.url && (
          <div className="flex items-center gap-1">
            <LinkIcon className="h-3.5 w-3.5" />
            <span className="text-[#1d9bf0] hover:underline truncate max-w-[150px]">
              {user.url.replace(/^https?:\/\//, "").replace(/\/$/, "")}
            </span>
          </div>
        )}
        {user.created_at && (
          <div className="flex items-center gap-1">
            <Calendar01Icon className="h-3.5 w-3.5" />
            <span>Joined {formatJoinDate(user.created_at)}</span>
          </div>
        )}
      </div>

      {/* Stats */}
      <div className="flex items-center gap-4 text-sm">
        <div className="flex items-center gap-1">
          <span className="font-bold text-foreground">
            {formatNumber(metrics.following_count)}
          </span>
          <span className="text-default-500">Following</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="font-bold text-foreground">
            {formatNumber(metrics.followers_count)}
          </span>
          <span className="text-default-500">Followers</span>
        </div>
      </div>
    </div>
  );
}

/**
 * Twitter User Section - Displays a list of Twitter users.
 * Used for search results, followers, and following lists.
 */
export default function TwitterUserSection({
  twitter_user_data,
  title,
  onFollow,
}: {
  twitter_user_data: TwitterUserData[];
  title?: string;
  onFollow?: (userId: string) => void;
}) {
  if (!twitter_user_data || twitter_user_data.length === 0) {
    return (
      <div className="mt-3 p-4 text-center text-default-500">
        No users found.
      </div>
    );
  }

  return (
    <div className="mt-3 flex w-full flex-col gap-3">
      {title && <p className="text-xs text-default-500 px-1">{title}</p>}
      <div className="flex flex-col gap-2">
        {twitter_user_data.map((user) => (
          <TwitterUserCard key={user.id} user={user} onFollow={onFollow} />
        ))}
      </div>
    </div>
  );
}
