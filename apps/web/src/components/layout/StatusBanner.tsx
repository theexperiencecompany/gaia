"use client";

import { Alert01Icon, Cancel01Icon } from "@icons";
import axios from "axios";
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
      const res = await axios.get(PING_URL);
      if (res.status >= 200 && res.status < 300) {
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
            className="underline underline-offset-2 hover:text-amber-300"
          >
            Learn more
          </Link>
        </span>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="shrink-0 rounded p-0.5 hover:bg-amber-500/20"
      >
        <Cancel01Icon className="size-4" />
      </button>
    </div>
  );
}
