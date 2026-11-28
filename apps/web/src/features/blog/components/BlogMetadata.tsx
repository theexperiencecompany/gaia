import { FIXED_LOCALE, formatDate } from "@shared/utils";
import { parseISO } from "date-fns";
import type { Author } from "@/lib/blog.types";

import { AuthorTooltip } from "./AuthorTooltip";
import CopyLinkButton from "./CopyLinkButton";

interface BlogMetadataProps {
  authors?: Author[];
  date: string;
  /** Revision date — renders a visible "Updated" label when set. */
  updated?: string;
  className?: string;
}

export default function BlogMetadata({
  authors,
  date,
  updated,
  className = "",
}: BlogMetadataProps) {
  const showUpdated = updated !== undefined && updated !== date;
  return (
    <div className={`flex items-center justify-center space-x-4 ${className}`}>
      <div className="flex -space-x-2">
        {(authors || []).map((author) => {
          const authorData: Author = {
            name: author.name,
            avatar:
              author.avatar || `https://api.pravatar.cc/40?u=${author.name}`,
            role: author.role,
            linkedin: author.linkedin,
            twitter: author.twitter,
          };
          return (
            <AuthorTooltip
              key={author.name}
              author={authorData}
              avatarSize="md"
              avatarClassName="h-10 w-10 cursor-help border-2 border-background"
            />
          );
        })}
      </div>
      <div>·</div>
      <div>
        <div className="text-zinc-400 flex items-center text-sm">
          <span className="text-zinc-400">
            {formatDate(parseISO(date), "long", { locale: FIXED_LOCALE })}
          </span>
          {showUpdated && (
            <span className="text-zinc-400">
              &nbsp;(Updated{" "}
              {formatDate(parseISO(updated), "long", { locale: FIXED_LOCALE })})
            </span>
          )}
        </div>
      </div>
      <div>·</div>
      <CopyLinkButton />
    </div>
  );
}
