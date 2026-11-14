"use client";

import { Button } from "@heroui/button";
import { Link as HeroLink } from "@heroui/link";
import { ArrowLeft01Icon } from "@icons";
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

import { useAuth } from "@/features/auth/hooks/useAuth";

/**
 * A full page outside the app shell (no sidebar): a brief opened from its email
 * or chat link, or anything shared through heygaia.link. GAIA wordmark, a
 * "Back to chats" button for signed-in readers only, and a centred column.
 */
interface StandalonePageProps {
  children: ReactNode;
  /** "wide" for documents laid out in columns (artifacts); "reading" otherwise. */
  width?: "reading" | "wide";
  /** Page actions beside the header's navigation (a download, say). */
  actions?: ReactNode;
}

const COLUMN_WIDTH = { reading: "max-w-3xl", wide: "max-w-5xl" } as const;

export function StandalonePage({
  children,
  width = "reading",
  actions,
}: StandalonePageProps) {
  const { isAuthenticated } = useAuth();
  return (
    <main className="min-h-dvh w-full bg-primary-bg px-4 py-6">
      <div className={`mx-auto w-full space-y-4 ${COLUMN_WIDTH[width]}`}>
        <div className="flex items-center justify-between gap-4">
          <HeroLink as={Link} href="/" aria-label="GAIA home">
            <Image
              src="/images/logos/text_w_logo_white.webp"
              alt="GAIA"
              width={88}
              height={26}
              className="object-contain"
            />
          </HeroLink>
          <div className="flex items-center gap-2">
            {actions}
            {isAuthenticated && (
              <Button
                as={Link}
                href="/c"
                variant="flat"
                size="sm"
                startContent={<ArrowLeft01Icon className="size-4" />}
              >
                Back to chats
              </Button>
            )}
          </div>
        </div>
        {children}
      </div>
    </main>
  );
}
