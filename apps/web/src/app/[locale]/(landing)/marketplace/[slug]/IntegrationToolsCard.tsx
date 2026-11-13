import { Card } from "@heroui/react";
import { PackageOpenIcon } from "@icons";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import { ToolDescription } from "./ToolDescription";
import { ToolList } from "./ToolList";
import { displayToolDescription, displayToolName } from "./toolCopy";

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

/** Every tool, rendered on the server: the markdown parser never ships to the browser. */
export function IntegrationToolsCard({
  integration,
}: {
  integration: PublicIntegrationResponse;
}) {
  const hasTools = Boolean(integration.tools && integration.tools.length > 0);

  return (
    <Card className="bg-zinc-900/50 backdrop-blur-md outline-0 border-none rounded-3xl">
      {hasTools && (
        <Card.Header>
          <h2 className="text-lg font-normal">
            Available Tools ({integration.toolCount})
          </h2>
        </Card.Header>
      )}
      <Card.Content>
        {hasTools ? (
          <ToolList
            items={(integration.tools ?? []).map((tool) => ({
              key: tool.name,
              label: displayToolName(tool.name, integration.name),
              description: tool.description ? (
                <ToolDescription
                  markdown={displayToolDescription(
                    tool.description,
                    integration.name,
                  )}
                />
              ) : null,
            }))}
          />
        ) : (
          <EmptyTools />
        )}
      </Card.Content>
    </Card>
  );
}
