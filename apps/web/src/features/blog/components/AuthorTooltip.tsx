import { Avatar } from "@heroui/avatar";
import { Link } from "@heroui/link";
import { Tooltip } from "@heroui/tooltip";

import { Github, LinkedinIcon, TwitterIcon } from "@/components/shared/icons";
import type { Author } from "@/types/api/aboutApiTypes";

interface AuthorTooltipProps {
  author: Author;
  avatarSize?: "sm" | "md" | "lg";
  avatarClassName?:
    | "h-6 w-6 cursor-help"
    | "h-8 w-8 cursor-help"
    | "h-10 w-10 cursor-help";
  /** Ring that separates overlapping avatars in -space-x stacks. Rendered on
   * a plain wrapper (not the Avatar) so the Avatar keeps static classes. */
  stacked?: boolean;
}

export function AuthorTooltip({
  author,
  avatarSize = "sm",
  avatarClassName = "h-8 w-8 cursor-help",
  stacked = false,
}: AuthorTooltipProps) {
  const avatar = (
    <Avatar
      src={author.avatar}
      size={avatarSize}
      className={
        avatarClassName === "h-6 w-6 cursor-help"
          ? "h-6 w-6 cursor-help"
          : avatarClassName === "h-10 w-10 cursor-help"
            ? "h-10 w-10 cursor-help"
            : "h-8 w-8 cursor-help"
      }
      name={author.name}
    />
  );
  return (
    <Tooltip
      content={
        <div className="flex flex-row items-center gap-3 p-2">
          <Avatar
            src={author.avatar}
            size="sm"
            className="h-8 w-8"
            name={author.name}
          />
          <div className="flex flex-col">
            <span className="text-medium">{author.name}</span>
            <span className="text-xs text-foreground-500">{author.role}</span>
          </div>
          <div className="mt-1 ml-6 flex gap-2">
            {author.linkedin && (
              <Link href={author.linkedin} isExternal>
                <LinkedinIcon width={20} height={20} />
              </Link>
            )}
            {author.twitter && (
              <Link href={author.twitter} isExternal>
                <TwitterIcon width={20} height={20} />
              </Link>
            )}

            {author.github && (
              <Link href={author.github} isExternal>
                <Github width={20} height={20} />
              </Link>
            )}
          </div>
        </div>
      }
      classNames={{ content: "text-nowrap" }}
    >
      {stacked ? (
        <div className="rounded-full border-2 border-background">{avatar}</div>
      ) : (
        avatar
      )}
    </Tooltip>
  );
}
