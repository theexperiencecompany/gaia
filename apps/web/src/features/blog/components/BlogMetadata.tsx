import type { Author } from "@/types/api/aboutApiTypes";
import { formatRelativeDate } from "@/utils/date/dateUtils";

import { AuthorTooltip } from "./AuthorTooltip";
import CopyLinkButton from "./CopyLinkButton";

interface TeamMember {
  id?: string;
  name: string;
  role: string;
  avatar?: string;
  linkedin?: string;
  twitter?: string;
}

interface BlogMetadataProps {
  authors?: TeamMember[];
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
              key={author.id || author.name}
              author={authorData}
              avatarSize="md"
              avatarClassName="h-10 w-10 cursor-help border-2 border-background"
            />
          );
        })}
      </div>
      <div>·</div>
      <div>
        <div className="text-muted-foreground flex items-center text-sm">
          <span className="text-foreground-500">
            {formatRelativeDate(date)}
          </span>
          {showUpdated && (
            <span className="text-foreground-500">
              &nbsp;(Updated {formatRelativeDate(updated)})
            </span>
          )}
        </div>
      </div>
      <div>·</div>
      <CopyLinkButton />
    </div>
  );
}
