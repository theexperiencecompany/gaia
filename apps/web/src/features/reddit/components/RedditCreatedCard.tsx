"use client";

import { Chip } from "@heroui/chip";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { CheckmarkCircle02Icon, LinkSquare02Icon } from "@icons";
import Link from "next/link";
import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { RedditIcon } from "@/components/shared/icons";
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
    <div className="w-full max-w-2xl rounded-3xl bg-zinc-800 p-3 text-white">
      <ScrollShadow className="max-h-[400px]">
        <div className="divide-y divide-zinc-800">
          {allItems.map((item) => (
            <div key={item.data.id} className="space-y-3 p-3">
              <div className="flex items-center gap-2">
                <CheckmarkCircle02Icon className="h-5 w-5 text-emerald-400" />
                <span className="text-sm font-semibold text-emerald-400">
                  {item.type === "post"
                    ? "Post Created Successfully!"
                    : "Comment Posted Successfully!"}
                </span>
                <Chip
                  size="sm"
                  variant="flat"
                  color="success"
                  className="ml-auto text-xs text-emerald-400"
                >
                  Just now
                </Chip>
              </div>

              <div className="text-sm text-zinc-300">{item.data.message}</div>

              <div className="flex items-center justify-between pt-2">
                {item.data.id && (
                  <div className="text-xs text-zinc-500">
                    ID:{" "}
                    <span className="font-mono text-zinc-400 tabular-nums">
                      {item.data.id}
                    </span>
                  </div>
                )}

                {item.data.permalink && (
                  <Link
                    href={`https://reddit.com${item.data.permalink}`}
                    target="_blank"
                    className="ml-auto flex items-center gap-1.5 text-xs text-orange-500 transition-colors hover:text-orange-400"
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
                      className="ml-auto flex items-center gap-1.5 text-xs text-orange-500 transition-colors hover:text-orange-400"
                    >
                      View on Reddit
                      <LinkSquare02Icon className="h-3.5 w-3.5" />
                    </Link>
                  )}
              </div>
            </div>
          ))}
        </div>
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
