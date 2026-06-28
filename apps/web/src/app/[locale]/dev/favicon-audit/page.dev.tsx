"use client";

import { Card, CardBody } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import { useState } from "react";

import { apiService } from "@/lib/api/service";

interface FaviconAuditItem {
  integrationId: string;
  name: string;
  source: string;
  managedBy: string;
  serverUrl: string;
  storedIconUrl: string | null;
  beforeUrl: string;
  afterUrl: string | null;
  changed: boolean;
}

interface FaviconAuditResponse {
  environment: string;
  total: number;
  changed: number;
  items: FaviconAuditItem[];
}

function FaviconImg({ url }: { url: string | null }) {
  const [hasError, setHasError] = useState(false);
  if (!url || hasError) {
    return (
      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-zinc-700 text-[10px] text-zinc-400">
        none
      </div>
    );
  }
  // unoptimized: before/after URLs are arbitrary remote favicon hosts that
  // aren't (and can't be) enumerated in next/image remotePatterns.
  return (
    <Image
      src={url}
      alt="favicon"
      width={48}
      height={48}
      unoptimized
      className="h-12 w-12 rounded-lg bg-zinc-900 object-contain p-1"
      onError={() => setHasError(true)}
    />
  );
}

function Column({ label, url }: { label: string; url: string | null }) {
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-[10px] uppercase tracking-wide text-zinc-500">
        {label}
      </span>
      <FaviconImg url={url} />
    </div>
  );
}

export default function FaviconAuditPage() {
  const { data, isLoading, error } = useQuery<FaviconAuditResponse>({
    queryKey: ["dev", "favicon-audit"],
    queryFn: () =>
      apiService.get<FaviconAuditResponse>("/dev/favicon-audit", {
        silent: true,
      }),
    staleTime: 0,
  });

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="text-2xl font-semibold text-white">
        Favicon resolver — before / after
      </h1>
      <p className="mt-1 text-sm text-zinc-400">
        Legacy (Google S2 on registered domain) vs patched (per-host) favicon
        resolution for every MCP server in production.
      </p>

      {isLoading && (
        <div className="mt-10 flex justify-center">
          <Spinner />
        </div>
      )}

      {error && (
        <p className="mt-6 text-sm text-red-400">
          Failed to load. This endpoint is dev-only (the API must run with
          ENV=development).
        </p>
      )}

      {data && (
        <>
          <div className="mt-4 flex gap-2">
            <Chip size="sm" variant="flat">
              {data.total} MCP servers
            </Chip>
            <Chip size="sm" variant="flat" color="warning">
              {data.changed} changed
            </Chip>
            <Chip size="sm" variant="flat">
              env: {data.environment}
            </Chip>
          </div>

          <div className="mt-6 flex flex-col gap-3">
            {data.items.map((item) => (
              <Card
                key={`${item.source}:${item.integrationId}`}
                className={
                  item.changed
                    ? "border border-warning-500/40 bg-zinc-800"
                    : "bg-zinc-800"
                }
              >
                <CardBody className="flex flex-row items-center gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium text-white">
                        {item.name}
                      </span>
                      <Chip size="sm" variant="flat">
                        {item.source}
                      </Chip>
                      <Chip size="sm" variant="flat">
                        {item.managedBy}
                      </Chip>
                      {item.changed && (
                        <Chip size="sm" variant="flat" color="warning">
                          changed
                        </Chip>
                      )}
                    </div>
                    <p className="mt-1 truncate text-xs text-zinc-500">
                      {item.serverUrl}
                    </p>
                  </div>
                  <Column label="Before" url={item.beforeUrl} />
                  <Column label="After" url={item.afterUrl} />
                </CardBody>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
