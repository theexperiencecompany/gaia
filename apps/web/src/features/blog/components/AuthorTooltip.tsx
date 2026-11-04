import { Avatar, Tooltip } from "@heroui/react";

import { Github, LinkedinIcon, TwitterIcon } from "@/components/shared/icons";
import type { Author } from "@/types/api/aboutApiTypes";

interface AuthorTooltipProps {
  author: Author;
  avatarSize?: "sm" | "md" | "lg";
  avatarClassName?: string;
}

/** The initials shown in the avatar when its image fails to load. */
function initialsOf(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function AuthorTooltip({
  author,
  avatarSize = "sm",
  avatarClassName = "h-8 w-8 cursor-help border-2 border-zinc-700",
}: AuthorTooltipProps) {
  const initials = initialsOf(author.name);
  return (
    <Tooltip>
      <Tooltip.Trigger>
        <Avatar size={avatarSize} className={avatarClassName}>
          <Avatar.Image
            src={author.avatar}
            alt={author.role ? `${author.name}, ${author.role}` : author.name}
            width={32}
            height={32}
            loading="lazy"
            decoding="async"
          />
          <Avatar.Fallback>{initials}</Avatar.Fallback>
        </Avatar>
      </Tooltip.Trigger>
      <Tooltip.Content className="text-nowrap">
        <div className="flex flex-row items-center gap-3 p-2">
          <Avatar size="sm" className="h-8 w-8">
            <Avatar.Image
              src={author.avatar}
              alt=""
              width={32}
              height={32}
              loading="lazy"
              decoding="async"
            />
            <Avatar.Fallback>{initials}</Avatar.Fallback>
          </Avatar>
          <div className="flex flex-col">
            <span className="text-medium">{author.name}</span>
            <span className="text-xs text-foreground-500">{author.role}</span>
          </div>
          <div className="mt-1 ml-6 flex gap-2">
            {author.linkedin && (
              <a
                href={author.linkedin}
                target="_blank"
                rel="noopener noreferrer"
              >
                <LinkedinIcon width={20} height={20} />
              </a>
            )}
            {author.twitter && (
              <a
                href={author.twitter}
                target="_blank"
                rel="noopener noreferrer"
              >
                <TwitterIcon width={20} height={20} />
              </a>
            )}

            {author.github && (
              <a href={author.github} target="_blank" rel="noopener noreferrer">
                <Github width={20} height={20} />
              </a>
            )}
          </div>
        </div>
      </Tooltip.Content>
    </Tooltip>
  );
}
