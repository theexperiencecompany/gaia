import { Card, CardBody, CardHeader } from "@heroui/card";
import { ScrollShadow } from "@heroui/react";
import { PackageOpenIcon } from "@icons";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import { ToolCard } from "./ToolCard";

function EmptyTools() {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      <PackageOpenIcon
        width={48}
        height={48}
        className="text-foreground-300 mb-4"
      />
      <p className="text-foreground-400 max-w-md text-sm">
        This integration might not have tools available yet because no one has
        connected to it, or the tools haven&apos;t been synced. Try refreshing
        the page.
      </p>
    </div>
  );
}

export function IntegrationToolsCard({
  integration,
}: {
  integration: PublicIntegrationResponse;
}) {
  const hasTools = Boolean(integration.tools && integration.tools.length > 0);

  return (
    <Card className="bg-zinc-900/50 backdrop-blur-md outline-0 border-none rounded-3xl">
      {hasTools && (
        <CardHeader>
          <h2 className="text-lg font-normal">
            Available Tools ({integration.toolCount})
          </h2>
        </CardHeader>
      )}
      <CardBody>
        {hasTools ? (
          <ScrollShadow className="max-h-100">
            <div className="grid grid-cols-2 gap-4">
              {integration.tools?.map((tool) => (
                <ToolCard
                  key={tool.name}
                  name={tool.name}
                  description={tool.description}
                  integrationName={integration.name}
                />
              ))}
            </div>
          </ScrollShadow>
        ) : (
          <EmptyTools />
        )}
      </CardBody>
    </Card>
  );
}
