"use client";

import { Link } from "@heroui/link";
import Image from "next/image";
import { memo, useState } from "react";

interface TodoLinkPreviewProps {
  href: string;
}

function extractDomain(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function getFaviconUrl(url: string): string {
  try {
    const parsed = new URL(url);
    return `https://www.google.com/s2/favicons?domain=${parsed.hostname}&sz=16`;
  } catch {
    return "";
  }
}

export const TodoLinkPreview = memo(function TodoLinkPreview({
  href,
}: TodoLinkPreviewProps) {
  const domain = extractDomain(href);
  const faviconUrl = getFaviconUrl(href);
  const [faviconFailed, setFaviconFailed] = useState(false);

  return (
    <Link
      href={href}
      isExternal
      aria-label={`${domain} (opens in new tab)`}
      onClick={(e) => e.stopPropagation()}
      className="inline-flex items-center gap-1 underline decoration-zinc-500 underline-offset-2 transition-colors hover:text-primary"
    >
      {faviconUrl && !faviconFailed && (
        <Image
          src={faviconUrl}
          alt=""
          aria-hidden="true"
          width={16}
          height={16}
          className="inline-block size-4 shrink-0 rounded-sm"
          onError={() => setFaviconFailed(true)}
        />
      )}
      <span>{domain}</span>
    </Link>
  );
});
