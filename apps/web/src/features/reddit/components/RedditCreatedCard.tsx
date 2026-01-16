"use client";

import { Chip } from "@heroui/chip";
import { ScrollShadow } from "@heroui/scroll-shadow";
import Link from "next/link";

import { RedditIcon } from "@/components";
import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { CheckmarkCircle02Icon, LinkSquare02Icon } from "@/icons";
import type {
  RedditCommentCreatedData,
  RedditPostCreatedData,
} from "@/types/features/redditTypes";

interface RedditCreatedCardProps {
  posts?: RedditPostCreatedData[];
  comments?: RedditCommentCreatedData[];
  isCollapsible?: boolean;
}

export default function RedditCreatedCard({
  posts = [],
  comments = [],
  isCollapsible = true,
}: RedditCreatedCardProps) {
  const totalCount = posts.length + comments.length;
  if (totalCount === 0) return null;

  const allItems = [
    ...posts.map((p) => ({ type: "post" as const, data: p })),
    ...comments.map((c) => ({ type: "comment" as const, data: c })),
  ];

  const content = (
    <div className="w-full max-w-2xl rounded-3xl bg-surface-200 p-3 text-foreground">
      <ScrollShadow className="max-h-[400px] divide-y divide-gray-700">
        {allItems.map((item) => (
          <div key={item.data.id} className="space-y-3 p-3">
            <div className="flex items-center gap-2">
              <CheckmarkCircle02Icon className="h-5 w-5 text-green-400" />
              <span className="text-sm font-semibold text-green-400">
                {item.type === "post"
                  ? "Post Created Successfully!"
                  : "Comment Posted Successfully!"}
              </span>
              <Chip
                size="sm"
                variant="flat"
                className="ml-auto bg-green-900/30 text-xs text-green-300"
              >
                Just now
              </Chip>
            </div>

            <div className="text-sm text-foreground-300">{item.data.message}</div>

            <div className="flex items-center justify-between pt-2">
              {item.data.id && (
                <div className="text-xs text-foreground-500">
                  ID:{" "}
                  <span className="font-mono text-foreground-400">
                    {item.data.id}
                  </span>
                </div>
              )}

              {item.data.permalink && (
                <Link
                  href={`https://reddit.com${item.data.permalink}`}
                  target="_blank"
                  className="ml-auto flex items-center gap-1.5 text-xs text-[#FF4500] transition-colors hover:text-orange-300"
                >
                  View on Reddit
                  <LinkSquare02Icon className="h-3.5 w-3.5" />
                </Link>
              )}
              {item.type === "post" &&
                !item.data.permalink &&
                (item.data as RedditPostCreatedData).url && (
                  <Link
                    href={(item.data as RedditPostCreatedData).url || ""}
                    target="_blank"
                    className="ml-auto flex items-center gap-1.5 text-xs text-[#FF4500] transition-colors hover:text-orange-300"
                  >
                    View on Reddit
                    <LinkSquare02Icon className="h-3.5 w-3.5" />
                  </Link>
                )}
            </div>
          </div>
        ))}
      </ScrollShadow>
    </div>
  );

  return (
    <CollapsibleListWrapper
      icon={<RedditIcon color="#FF4500" />}
      count={totalCount}
      label={totalCount === 1 ? "Action Completed" : "Actions Completed"}
      isCollapsible={isCollapsible}
    >
      {content}
    </CollapsibleListWrapper>
  );
}
