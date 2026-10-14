import { Link } from "@heroui/link";
import Image from "next/image";
import type { ReactNode } from "react";

import { BackToChatsButton } from "./BackToChatsButton";

interface PublicLinkShellProps {
  children: ReactNode;
}

/**
 * The one standalone frame for every heygaia.link page, whatever the target:
 * GAIA wordmark, a "Back to chats" button for signed-in viewers, a centred
 * reading column and a quiet footer. Rendered outside the authed app shell (no
 * sidebar) — the viewer is usually signed out, tapping a link inside a chat
 * app or an email. Children are the target's own view, e.g. the standalone
 * brief component.
 */
export function PublicLinkShell({ children }: PublicLinkShellProps) {
  return (
    <div className="flex min-h-dvh w-full flex-col bg-primary-bg">
      <header className="sticky top-0 z-10 shrink-0 bg-primary-bg/80 px-6 py-4 backdrop-blur-xl">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-4">
          <Link href="/" aria-label="GAIA home">
            <Image
              src="/images/logos/text_w_logo_white.webp"
              alt="GAIA"
              width={88}
              height={26}
              className="object-contain"
            />
          </Link>
          <BackToChatsButton />
        </div>
      </header>

      <main className="flex-1 px-6 pb-16 pt-2">
        <div className="mx-auto max-w-3xl">{children}</div>
      </main>

      <footer className="px-6 pb-8 text-center text-xs text-zinc-500">
        Shared from{" "}
        <Link href="/" className="text-xs text-zinc-400" underline="hover">
          GAIA
        </Link>
        , your proactive personal assistant.
      </footer>
    </div>
  );
}
