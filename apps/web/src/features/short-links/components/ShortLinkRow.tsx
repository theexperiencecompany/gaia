"use client";

import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import { Copy01Icon, Link01Icon } from "@icons";

import {
  copyShortLink,
  displayShortLink,
} from "@/features/short-links/utils/copyShortLink";

/**
 * An artifact's heygaia.link with a copy button. Stops press propagation so it
 * can sit inside a pressable card without also opening it.
 */
export function ShortLinkRow({ url }: { url: string }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Link01Icon size={12} className="shrink-0 text-zinc-500" />
      <Link
        href={url}
        isExternal
        size="sm"
        className="min-w-0 truncate text-xs text-zinc-400 hover:text-zinc-200"
        onClick={(event) => event.stopPropagation()}
      >
        {displayShortLink(url)}
      </Link>
      <Button
        isIconOnly
        size="sm"
        variant="light"
        className="h-6 w-6 min-w-6 text-zinc-400"
        aria-label="Copy link"
        onClick={(event) => event.stopPropagation()}
        onPress={() => copyShortLink(url)}
      >
        <Copy01Icon size={12} />
      </Button>
    </div>
  );
}
