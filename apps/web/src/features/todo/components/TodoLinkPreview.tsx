"use client";

import Image from "next/image";
import { memo } from "react";

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

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={handleClick}
      className="inline-flex items-center gap-1 underline decoration-zinc-500 underline-offset-2 transition-colors hover:text-primary"
    >
      {faviconUrl && (
        <Image
          src={faviconUrl}
          alt=""
          width={14}
          height={14}
          className="inline-block h-3.5 w-3.5 shrink-0 rounded-sm"
        />
      )}
      <span>{domain}</span>
    </a>
  );
});
