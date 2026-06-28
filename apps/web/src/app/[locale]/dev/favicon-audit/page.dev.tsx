"use client";

import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { useQuery } from "@tanstack/react-query";

import { IntegrationIcon } from "@/features/integrations/components/PublicIntegrationCard";
import { apiService } from "@/lib/api/service";

interface FaviconAuditItem {
  integrationId: string;
  name: string;
  source: string;
  managedBy: string;
  serverUrl: string | null;
  storedIconUrl: string | null;
  beforeUrl: string | null;
  afterUrl: string | null;
  changed: boolean;
}

interface FaviconAuditResponse {
  environment: string;
  total: number;
  changed: number;
  items: FaviconAuditItem[];
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
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-semibold text-white">
        Public integration icons
      </h1>
      <p className="mt-1 text-sm text-zinc-400">
        How every production public integration renders in the marketplace. MCP
        servers use the patched per-host favicon resolver; a green ring marks
        one whose icon the patch improved.
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
              {data.total} integrations
            </Chip>
            <Chip size="sm" variant="flat" color="success">
              {data.changed} favicons improved
            </Chip>
            <Chip size="sm" variant="flat">
              env: {data.environment}
            </Chip>
          </div>

          <div className="mt-6 grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
            {data.items.map((item) => (
              <div
                key={`${item.source}:${item.integrationId}`}
                className="flex flex-col items-center gap-2 rounded-xl bg-zinc-800 p-3 text-center"
                title={`${item.name} (${item.source}/${item.managedBy})`}
              >
                <div
                  className={`flex h-12 w-12 items-center justify-center rounded-lg bg-zinc-900 ${
                    item.changed ? "ring-2 ring-success-500" : ""
                  }`}
                >
                  <IntegrationIcon
                    integrationId={item.integrationId}
                    iconUrl={item.afterUrl ?? item.storedIconUrl}
                  />
                </div>
                <span className="line-clamp-2 text-[11px] leading-tight text-zinc-300">
                  {item.name}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
