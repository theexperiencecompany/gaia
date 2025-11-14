"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import React from "react";

import { Separator, SidebarHeader } from "@/components/ui";
import { SidebarContent } from "@/components/ui/shadcn/sidebar";
import { useToolsWithIntegrations } from "@/features/chat/hooks/useToolsWithIntegrations";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { Integration } from "@/features/integrations/types";

interface IntegrationSidebarProps {
  integration: Integration;
  onConnect: (integrationId: string) => void;
  category?: string;
}

export const IntegrationSidebar: React.FC<IntegrationSidebarProps> = ({
  integration,
  onConnect,
  category,
}) => {
  const isConnected = integration.status === "connected";
  const isAvailable = !!integration.loginEndpoint;
  const { tools } = useToolsWithIntegrations();

  // Get tools that belong to this integration or its included integrations
  const integrationTools = React.useMemo(() => {
    const integrationIds = [
      integration.id,
      ...(integration.includedIntegrations || []),
    ].map((id) => id.toLowerCase());

    console.log({ integrationIds, integration });

    return tools.filter((tool) =>
      integrationIds.includes(
        tool.integration?.requiredIntegration.toLowerCase() || "",
      ),
    );
  }, [tools, integration.id, integration.includedIntegrations]);

  const handleConnect = () => {
    if (isAvailable && !isConnected) {
      onConnect(integration.id);
    }
  };

  return (
    <div className="flex h-full max-h-[calc(100vh-60px)] flex-col px-5">
      <SidebarHeader>
        {getToolCategoryIcon(integration.id, {
          size: 40,
          width: 40,
          height: 40,
          showBackground: true,
        })}

        <div className="mb-0 flex flex-col items-start gap-1">
          <div className="flex w-full items-center justify-between">
            <h1 className="text-2xl font-semibold text-zinc-100">
              {integration.name}
            </h1>

            {isConnected && (
              <Chip size="sm" variant="flat" color="success">
                Connected
              </Chip>
            )}
            {!isAvailable && (
              <Chip size="sm" variant="flat" color="default">
                Coming Soon
              </Chip>
            )}
          </div>

          <p className="text-sm leading-relaxed font-light text-zinc-400">
            {integration.description}
          </p>
        </div>

        {!isConnected && (
          <Button
            color="primary"
            fullWidth
            onPress={handleConnect}
            isDisabled={!isAvailable}
          >
            {isAvailable ? "Connect" : "Coming Soon"}
          </Button>
        )}
        <Separator className="my-3 bg-zinc-800" />
        <h2 className="mb-2 text-sm font-medium text-zinc-300">
          Available Tools ({integrationTools.length})
        </h2>
      </SidebarHeader>
      <SidebarContent className="flex-1 overflow-y-auto">
        <div className="space-y-4 pb-4">
          {integrationTools.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {integrationTools.map((tool) => (
                <Chip
                  key={tool.name}
                  variant="flat"
                  color="default"
                  startContent={
                    tool.integration?.requiredIntegration &&
                    getToolCategoryIcon(tool.integration.requiredIntegration, {
                      size: 18,
                      width: 18,
                      height: 18,
                      showBackground: false,
                    })
                  }
                >
                  {category
                    ? formatToolName(tool.name)
                        .replace(new RegExp(`^${category}\\s*`, "gi"), "")
                        .trim()
                    : formatToolName(tool.name)}
                </Chip>
              ))}
            </div>
          )}
        </div>
      </SidebarContent>
    </div>
  );
};
