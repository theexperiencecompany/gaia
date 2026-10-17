"use client";

import { Card, CardBody, CardHeader } from "@heroui/card";
import { ScrollShadow } from "@heroui/react";
import { PackageOpenIcon } from "@icons";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import { ToolCard } from "./ToolCard";

/** The "Available tools" card: the synced tool grid, or the empty state. */
export function IntegrationToolsCard({
  integration,
}: {
  readonly integration: PublicIntegrationResponse;
}) {
  return (
    <Card className="bg-zinc-900/50 backdrop-blur-md outline-0 border-none rounded-3xl">
      {integration.tools && integration.tools.length > 0 && (
        <CardHeader>
          <h2 className="text-lg font-normal">
            Available Tools ({integration.toolCount})
          </h2>
        </CardHeader>
      )}
      <CardBody>
        {integration.tools && integration.tools.length > 0 ? (
          <ScrollShadow className="max-h-100">
            <div className="grid grid-cols-2 gap-4">
              {integration.tools.map((tool) => (
                <ToolCard
                  key={tool.name}
                  name={tool.name}
                  description={tool.description}
                />
              ))}
            </div>
          </ScrollShadow>
        ) : (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <PackageOpenIcon
              width={48}
              height={48}
              className="text-foreground-300 mb-4"
            />
            <p className="text-foreground-400 max-w-md text-sm">
              This integration might not have tools available yet because no one
              has connected to it, or the tools haven&apos;t been synced. Try
              refreshing the page.
            </p>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
