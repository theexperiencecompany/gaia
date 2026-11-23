"use client";

import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

import { ChevronLeft } from "@/components/shared/icons";
import { LinkButton } from "@/components/shared/LinkButton";
import { useAuth } from "@/features/auth/hooks/useAuth";

/** Where a signed-in reader's back button leads, and what it says. */
export interface StandalonePageBack {
  href: string;
  label: string;
}

/**
 * A full page outside the app shell (no sidebar): a brief opened from its email
 * or chat link, or anything shared through heygaia.link. A back button for
 * signed-in readers, the GAIA wordmark centred, page actions opposite it, and
 * a centred column.
 */
interface StandalonePageProps {
  children: ReactNode;
  /** "letter" for one brief, "wide" for documents laid out in columns (artifacts); "reading" otherwise. */
  width?: "letter" | "reading" | "wide";
  /** Page actions opposite the back button (share, download). */
  actions?: ReactNode;
  back?: StandalonePageBack;
}

const COLUMN_WIDTH = {
  letter: "max-w-[572px]",
  reading: "max-w-3xl",
  wide: "max-w-5xl",
} as const;

const BACK_TO_CHATS: StandalonePageBack = { href: "/c", label: "Chats" };

export function StandalonePage({
  children,
  width = "reading",
  actions,
  back = BACK_TO_CHATS,
}: StandalonePageProps) {
  const { isAuthenticated } = useAuth();
  return (
    <main className="min-h-dvh w-full bg-primary-bg px-4 py-6">
      <div className={`mx-auto w-full space-y-6 ${COLUMN_WIDTH[width]}`}>
        <header className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
          <div className="flex min-w-0 items-center">
            {isAuthenticated && (
              <LinkButton
                href={back.href}
                variant="ghost"
                size="sm"
                inset="tight"
                tone="muted"
                hoverTone="strong"
                className="-ml-2 gap-1"
              >
                <ChevronLeft aria-hidden className="size-4" />
                {back.label}
              </LinkButton>
            )}
          </div>
          <Link href="/" aria-label="GAIA home">
            <Image
              src="/images/logos/text_w_logo_white.webp"
              alt="GAIA"
              width={88}
              height={26}
              className="object-contain"
            />
          </Link>
          <div className="flex min-w-0 items-center justify-end gap-2">
            {actions}
          </div>
        </header>
        {children}
      </div>
    </main>
  );
}
