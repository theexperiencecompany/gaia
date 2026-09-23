"use client";

import { Button } from "@heroui/button";
import { Alert01Icon, Cancel01Icon } from "@icons";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

const PING_URL =
  process.env.NODE_ENV === "development"
    ? `${process.env.NEXT_PUBLIC_API_BASE_URL}ping`
    : "https://api.heygaia.io/api/v1/ping";
const STATUS_URL = "https://status.heygaia.io";
const POLL_INTERVAL = 60_000;

export default function StatusBanner() {
  const [isDown, setIsDown] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const checkStatus = useCallback(async () => {
    try {
      // A status probe, not an API call: in production it targets the public
      // ping endpoint directly, so it stays off the app's API client.
      const res = await fetch(PING_URL, { cache: "no-store" });
      if (res.ok) {
        setIsDown(false);
      } else {
        setIsDown(true);
        setDismissed(false);
      }
    } catch {
      setIsDown(true);
      setDismissed(false);
    }
  }, []);

  useEffect(() => {
    checkStatus();
    intervalRef.current = setInterval(checkStatus, POLL_INTERVAL);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [checkStatus]);

  if (!isDown || dismissed) return null;

  return (
    <div className="flex w-full items-center justify-between gap-3 bg-amber-500/10 px-4 py-2 text-sm text-amber-400">
      <div className="flex items-center gap-2">
        <Alert01Icon className="size-4 shrink-0" />
        <span>
          We&apos;re experiencing some issues. Some features may be unavailable.{" "}
          <Link
            href={STATUS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 hover:text-amber-400"
          >
            Learn more
          </Link>
        </span>
      </div>
      <Button
        isIconOnly
        size="sm"
        variant="light"
        aria-label="Dismiss status banner"
        onPress={() => setDismissed(true)}
        className="shrink-0 text-amber-400"
      >
        <Cancel01Icon className="size-4" />
      </Button>
    </div>
  );
}
