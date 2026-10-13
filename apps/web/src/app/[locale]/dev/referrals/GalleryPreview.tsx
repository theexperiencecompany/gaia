"use client";

import { useEffect } from "react";
import { EmailPreview } from "@/features/chat/components/code-block/CustomAnchor";
import { InviteLanding } from "@/features/referrals/components/InviteLanding";
import { PostPaymentShareCard } from "@/features/referrals/components/PostPaymentShareCard";
import { SidebarReferralPromo } from "@/features/referrals/components/SidebarReferralPromo";
import {
  type InvitePhase,
  useInviteStore,
} from "@/features/referrals/stores/inviteStore";
import type { ReferralCopyVariant } from "@/features/referrals/types/contract";
import { offerPrices } from "@/features/referrals/utils/offerPrices";
import {
  FIXTURE_OFFER,
  FIXTURE_RESOLVE,
  fixtureSender,
  type GalleryView,
} from "./fixtures";

const SHARE_LINK = "https://heygaia.io/invite/aryan-k7f2";
const PRICES = offerPrices(FIXTURE_OFFER);
const noop = () => undefined;

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

function SidebarPreview({ copyVariant }: PreviewProps) {
  return (
    <div className="flex flex-wrap gap-10">
      <Frame label="Pro user, desktop sidebar (256px)">
        <div className="w-64 rounded-2xl bg-secondary-bg p-2">
          <SidebarReferralPromo
            url={SHARE_LINK}
            prices={PRICES}
            copyVariant={copyVariant}
          />
          {["Home", "Tasks", "Integrations", "Workflows", "Chats"].map(
            (label) => (
              <div key={label} className="px-3 py-1.5 text-sm text-zinc-400">
                {label}
              </div>
            ),
          )}
        </div>
      </Frame>
    </div>
  );
}

function PostPaymentPreview({ copyVariant }: PreviewProps) {
  return (
    <div className="mx-auto flex w-full max-w-sm flex-col gap-6">
      <div className="rounded-3xl bg-zinc-900/60 p-8 text-center">
        <h1 className="mb-2 text-2xl font-semibold text-white">
          Welcome to GAIA
        </h1>
        <p className="text-sm font-light text-zinc-400">
          You're all set, everything's unlocked. Let's go!
        </p>
      </div>
      <PostPaymentShareCard
        url={SHARE_LINK}
        prices={PRICES}
        copyVariant={copyVariant}
        onDismiss={noop}
      />
    </div>
  );
}

/** Frozen phases for the static cards; the "live" card runs the real hold-and-undo. */
const FROZEN: Record<string, InvitePhase> = {
  "sending@demo.gaia": { phase: "sending" },
  "held@demo.gaia": { phase: "held" },
  "sent@demo.gaia": { phase: "done", status: "sent" },
  "invited@demo.gaia": { phase: "done", status: "already_invited" },
};

const HOVER_CARDS = [
  {
    label: "Live (click it)",
    email: "jordan@northwind.co",
    name: "Jordan Lee",
  },
  { label: "Sending", email: "sending@demo.gaia", name: "Priya Shah" },
  { label: "Sent, undo window", email: "held@demo.gaia", name: "Marcus Webb" },
  { label: "Sent", email: "sent@demo.gaia", name: "Lena Fischer" },
  {
    label: "Already invited",
    email: "invited@demo.gaia",
    name: "Diego Alvarez",
  },
  {
    label: "Own address (hidden)",
    email: "aryan@heygaia.io",
    name: "Aryan",
    own: true,
  },
];

function HoverCardPreview() {
  useEffect(() => {
    useInviteStore.setState({ invites: { ...FROZEN } });
  }, []);

  return (
    <div className="flex flex-wrap gap-8">
      {HOVER_CARDS.map((card) => (
        <Frame key={card.email} label={card.label}>
          <div className="w-[280px] rounded-xl border-2 border-zinc-800 bg-secondary-bg p-3 text-white shadow-lg">
            <EmailPreview
              email={card.email}
              name={card.name}
              avatar={null}
              onAvatarError={noop}
              sendInvite={card.own ? undefined : fixtureSender}
            />
          </div>
        </Frame>
      ))}
    </div>
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
          {/* biome-ignore lint/performance/noImgElement: previews a dynamic dev route, next/image would re-encode it. */}
          <img
            src={`/dev/referrals/og?copy=${copyVariant}&fixture=${key}`}
            alt={`Invite OG image, ${key}`}
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
    case "sidebar":
      return <SidebarPreview copyVariant={copyVariant} />;
    case "post_payment":
      return <PostPaymentPreview copyVariant={copyVariant} />;
    case "hover_card":
      return <HoverCardPreview />;
    case "landing":
      return <LandingPreview copyVariant={copyVariant} />;
    case "og":
      return <OgPreview copyVariant={copyVariant} />;
  }
}
