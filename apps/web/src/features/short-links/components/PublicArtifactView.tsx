"use client";

import { Spinner } from "@heroui/spinner";
import { AlertCircleIcon } from "@icons";
import { useEffect, useState } from "react";

import RichContentRenderer from "@/features/chat/components/interface/RichContentRenderer";
import { apiService } from "@/lib/api/service";

interface PublicArtifact {
  title: string;
  content: string;
  todo_id: string;
  target_type: string;
}

interface PublicArtifactViewProps {
  slug: string;
}

/**
 * Public, read-only artifact page behind a heygaia.link capability slug — the
 * landing surface for briefing links tapped inside Telegram/WhatsApp, where the
 * viewer has no session. The slug itself is the authorization (resolved by the
 * unauthenticated `/l/{slug}` endpoint), so this renders outside the `(main)`
 * app shell with no auth gate; owner actions (approve/dismiss) live in the app,
 * never here.
 */
export function PublicArtifactView({ slug }: PublicArtifactViewProps) {
  const [artifact, setArtifact] = useState<PublicArtifact | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing">(
    "loading",
  );

  useEffect(() => {
    let cancelled = false;
    apiService
      .get<PublicArtifact>(`/l/${slug}`, { silent: true })
      .then((res) => {
        if (cancelled) return;
        setArtifact(res);
        setState("ready");
      })
      .catch(() => {
        if (!cancelled) setState("missing");
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  if (state === "loading") {
    return (
      <div className="flex min-h-dvh w-full items-center justify-center">
        <Spinner color="default" />
      </div>
    );
  }

  if (state === "missing" || !artifact) {
    return (
      <div className="flex min-h-dvh w-full flex-col items-center justify-center gap-2 text-center">
        <AlertCircleIcon width={24} height={24} className="text-zinc-500" />
        <p className="text-sm text-zinc-400">This link is not available.</p>
        <p className="text-xs text-zinc-500">
          It may have expired or been revoked.
        </p>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh w-full flex-col">
      <header className="sticky top-0 z-10 shrink-0 bg-primary-bg/80 px-6 py-4 backdrop-blur-xl">
        <div className="mx-auto max-w-3xl">
          <h1 className="min-w-0 truncate text-lg font-medium text-white">
            {artifact.title}
          </h1>
        </div>
      </header>

      <div className="flex-1 px-6 pb-16 pt-2">
        <div className="mx-auto max-w-3xl">
          {artifact.content ? (
            <RichContentRenderer
              content={artifact.content}
              className="text-base"
            />
          ) : (
            <p className="py-24 text-center text-sm text-zinc-500">
              This artifact is empty.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
