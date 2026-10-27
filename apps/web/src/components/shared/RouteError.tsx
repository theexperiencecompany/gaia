"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { Home01Icon } from "@icons";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { track } from "@/lib/analytics";
import {
  isChunkLoadError,
  recoverFromChunkError,
} from "@/lib/chunkErrorRecovery";

interface RouteErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

// Survives the boundary remounting when reset() re-throws. The pathname is part
// of the key so an unrelated route's error with the same message cannot inherit
// this one's failed attempt.
const RESET_ATTEMPT_KEY = "gaia:route-error-reset-at";
const RESET_ATTEMPT_WINDOW_MS = 30_000;

function readResetAttempt(): { key: string; at: number } | null {
  try {
    const raw = sessionStorage.getItem(RESET_ATTEMPT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * App Router segment error boundary. Rendered by `error.tsx` files so a render
 * error is contained to its route group (keeping the shell/nav alive) instead
 * of bubbling to `global-error.tsx` and replacing the whole document.
 */
export default function RouteError({ error, reset }: RouteErrorProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();
  const isChunk = isChunkLoadError(error);

  // Errors whose recovery attempt already concluded without a reload. Keyed by
  // the error itself — a brand-new error derives its own pending state during
  // render instead of syncing stale state over from a prop change.
  const [failedRecoveryErrors, setFailedRecoveryErrors] = useState<
    Set<unknown>
  >(() => new Set());

  useEffect(() => {
    // A stale-asset chunk failure reached the boundary. Reload once to fetch
    // fresh chunks; if recovery is exhausted, fall through to the retryable UI.
    if (isChunk) {
      if (recoverFromChunkError(error) === "reloading") return;
      setFailedRecoveryErrors((prev) => new Set(prev).add(error));
    }

    // Full diagnostics stay in the console (and Sentry). Only the stable,
    // non-sensitive name and digest go to analytics — error.message/stack can
    // carry backend responses, URLs, query params, or user content.
    console.error("Route error boundary caught:", error);
    track("error:route_error_shown", {
      error_type: "app_router_error_boundary",
      error_digest: error.digest,
      error_name: error.name,
      is_chunk_error: isChunk,
    });
  }, [error, isChunk]);

  const errorKey = `${pathname}|${error.name}:${error.digest ?? error.message}`;

  // A second press for the same error means reset did not clear it, so only a
  // full document load can; the button is disabled while the first is pending.
  const handleTryAgain = () => {
    const now = Date.now();
    const previous = readResetAttempt();
    if (
      previous?.key === errorKey &&
      now - previous.at < RESET_ATTEMPT_WINDOW_MS
    ) {
      sessionStorage.removeItem(RESET_ATTEMPT_KEY);
      window.location.reload();
      return;
    }
    sessionStorage.setItem(
      RESET_ATTEMPT_KEY,
      JSON.stringify({ key: errorKey, at: now }),
    );
    // reset alone re-renders the client tree; a server component that threw
    // (e.g. an unreachable API) only re-runs after a refresh.
    startTransition(() => {
      router.refresh();
      reset();
    });
  };

  // While the guarded reload decision is pending for a chunk error, show a
  // neutral loader rather than flashing the error UI for what is about to
  // become a fresh page.
  if (isChunk && !failedRecoveryErrors.has(error)) {
    return (
      <div className="flex min-h-[60vh] w-full items-center justify-center p-6">
        <Spinner color="primary" />
      </div>
    );
  }

  return (
    <div className="flex min-h-[60vh] w-full flex-col items-center justify-center gap-2 p-6 text-center">
      <h1 className="text-2xl font-bold text-white">Something went wrong</h1>
      <p className="max-w-md text-zinc-400">
        An unexpected error occurred. Please try again or return home.
      </p>
      <div className="flex items-center gap-3 pt-4">
        <Button color="primary" isDisabled={isPending} onPress={handleTryAgain}>
          Try again
        </Button>
        <Button
          variant="flat"
          startContent={<Home01Icon width={18} />}
          onPress={() => window.location.assign("/")}
        >
          Home
        </Button>
      </div>
    </div>
  );
}
