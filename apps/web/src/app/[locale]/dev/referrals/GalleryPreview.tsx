"use client";

import type { ReferralCopyVariant } from "@shared/api/generated";
import Image from "next/image";
import { InviteLanding } from "@/features/referrals/components/InviteLanding";
import { FIXTURE_RESOLVE, type GalleryView } from "./fixtures";

interface PreviewProps {
  copyVariant: ReferralCopyVariant;
}

function Frame({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="text-xs text-zinc-500">{label}</figcaption>
      {children}
    </figure>
  );
}

function LandingPreview({ copyVariant }: PreviewProps) {
  return (
    <div className="flex flex-col gap-10">
      {(["valid", "photo", "invalid"] as const).map((key) => (
        <Frame key={key} label={`Invite landing: ${key}`}>
          <div className="overflow-hidden rounded-3xl">
            <InviteLanding
              invite={FIXTURE_RESOLVE[key]}
              copyVariant={copyVariant}
              signupHref="/signup"
            />
          </div>
        </Frame>
      ))}
    </div>
  );
}

function OgPreview({ copyVariant }: PreviewProps) {
  return (
    <div className="flex flex-col gap-10">
      {(["valid", "photo"] as const).map((key) => (
        <Frame key={key} label={`1200x630, ${key}`}>
          {/* Unoptimized: the dev route renders the PNG under test, and re-encoding would alter it. */}
          <Image
            unoptimized
            src={`/dev/referrals/og?copy=${copyVariant}&fixture=${key}`}
            alt={
              key === "photo"
                ? "Invite link preview with the referrer's picture"
                : "Invite link preview without a picture"
            }
            width={1200}
            height={630}
            className="h-auto w-full max-w-[1200px] rounded-2xl"
          />
        </Frame>
      ))}
    </div>
  );
}

interface GalleryPreviewProps extends PreviewProps {
  view: Exclude<GalleryView, "page">;
}

export function GalleryPreview({ view, copyVariant }: GalleryPreviewProps) {
  switch (view) {
    case "landing":
      return <LandingPreview copyVariant={copyVariant} />;
    case "og":
      return <OgPreview copyVariant={copyVariant} />;
  }
}
