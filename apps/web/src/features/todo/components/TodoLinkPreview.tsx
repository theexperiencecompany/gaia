"use client";

import Image from "next/image";
import { memo, useState } from "react";

import { useUrlMetadata } from "@/features/chat/hooks/useUrlMetadata";

interface TodoLinkPreviewProps {
  href: string;
}

function getFallbackFaviconUrl(url: string): string {
  try {
    const parsed = new URL(url);
    return `https://www.google.com/s2/favicons?domain=${parsed.hostname}&sz=64`;
  } catch {
    return "";
  }
}

export const TodoLinkPreview = memo(function TodoLinkPreview({
  href,
}: TodoLinkPreviewProps) {
  const { data, isLoading } = useUrlMetadata(href);
  const [faviconFailed, setFaviconFailed] = useState(false);

  const label = data?.title?.trim() || href;
  const faviconUrl = data?.favicon || getFallbackFaviconUrl(href);

  // Plain <a> (not HeroUI Link) so the link is a normal inline element and
  // its text wraps as part of the surrounding paragraph. The parent h4's
  // line-clamp-2 then handles overall truncation at line two.
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      aria-label={`${label} (opens in new tab)`}
      onClick={(e) => e.stopPropagation()}
      className={`underline decoration-zinc-500 underline-offset-2 transition-colors hover:text-primary text-white px-0.5 ${isLoading ? "opacity-70" : ""}`}
    >
      {faviconUrl && !faviconFailed && (
        <Image
          src={faviconUrl}
          alt=""
          aria-hidden="true"
          width={20}
          height={20}
          style={{ verticalAlign: "-0.25em" }}
          className="mr-1 inline-block size-4 rounded-full"
          onError={() => setFaviconFailed(true)}
          unoptimized
        />
      )}
      {label}
    </a>
  );
});
