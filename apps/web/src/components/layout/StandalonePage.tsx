"use client";

import { ArrowLeft01Icon } from "@icons";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { LinkButton } from "@/components/shared/LinkButton";
import { useAuth } from "@/features/auth/hooks/useAuth";

/**
 * A full page outside the app shell (no sidebar): a brief opened from its email
 * or chat link, or anything shared through heygaia.link. GAIA wordmark, a
 * "Back to chats" button for signed-in readers only, and a centred column.
 */
export function StandalonePage({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  return (
    <main className="min-h-dvh w-full bg-primary-bg px-4 py-6">
      <div className="mx-auto w-full max-w-3xl space-y-4">
        <div className="flex items-center justify-between gap-4">
          <Link href="/" aria-label="GAIA home">
            <Image
              src="/images/logos/text_w_logo_white.webp"
              alt="GAIA"
              width={88}
              height={26}
              className="object-contain"
            />
          </Link>
          {isAuthenticated && (
            <LinkButton href="/c" variant="default-soft" size="sm">
              <ArrowLeft01Icon className="size-4" />
              Back to chats
            </LinkButton>
          )}
        </div>
        {children}
      </div>
    </main>
  );
}
