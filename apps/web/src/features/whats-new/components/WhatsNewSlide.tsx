"use client";

import Image from "next/image";
import type { Release } from "../types";
import { formatReleaseDate } from "../utils/formatReleaseDate";
import { WhatsNewContent } from "./WhatsNewContent";

const FALLBACK_IMAGE = "/images/whats-new-fallback.png";

interface WhatsNewSlideProps {
  release: Release;
  isFirst: boolean;
}

export function WhatsNewSlide({ release, isFirst }: WhatsNewSlideProps) {
  const heroImage = release.imageUrl ?? FALLBACK_IMAGE;

  return (
    <div className="flex flex-col gap-4 pb-2 pr-2">
      {/* Hero — full aspect-video height */}
      <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-zinc-800">
        <Image
          src={heroImage}
          alt={release.title}
          fill
          sizes="672px"
          className="object-cover"
          priority={isFirst}
        />
      </div>

      <span className="text-xs text-zinc-500">
        {formatReleaseDate(release.date)}
      </span>

      {/* Title — biggest element on the slide */}
      <h2 className="text-3xl font-semibold leading-snug text-white">
        {release.title}
      </h2>

      {/* Changelog body */}
      <WhatsNewContent html={release.html} />
    </div>
  );
}
