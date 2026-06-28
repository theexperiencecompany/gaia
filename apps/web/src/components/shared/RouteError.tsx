"use client";

import { Button } from "@heroui/button";
import { Home01Icon } from "@icons";
import { useEffect } from "react";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

interface RouteErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

/**
 * App Router segment error boundary. Rendered by `error.tsx` files so a render
 * error is contained to its route group (keeping the shell/nav alive) instead
 * of bubbling to `global-error.tsx` and replacing the whole document.
 */
export default function RouteError({ error, reset }: RouteErrorProps) {
  useEffect(() => {
    console.error("Route error boundary caught:", error);
    trackEvent(ANALYTICS_EVENTS.ERROR_OCCURRED, {
      error_type: "app_router_error_boundary",
      error_message: error.message,
      error_stack: error.stack,
      error_digest: error.digest,
    });
  }, [error]);

  return (
    <div className="flex min-h-[60vh] w-full flex-col items-center justify-center gap-2 p-6 text-center">
      <h1 className="text-2xl font-bold text-white">Something went wrong</h1>
      {error.message ? (
        <p className="max-w-md text-zinc-400">{error.message}</p>
      ) : null}
      <div className="flex items-center gap-3 pt-4">
        <Button color="primary" onPress={reset}>
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
