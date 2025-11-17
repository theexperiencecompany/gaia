import { Accordion, AccordionItem } from "@heroui/accordion";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Selection } from "@heroui/react";
import React from "react";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useIntegrationsAccordion } from "@/stores/uiStore";

import { Integration } from "../types";

interface IntegrationsCardProps {
  onClose?: () => void;
  onIntegrationClick?: (integrationId: string) => void;
  size?: "default" | "small";
}

const IntegrationItem: React.FC<{
  integration: Integration;
  onConnect: (id: string) => void;
  onClick: (id: string) => void;
  size?: "default" | "small";
}> = ({ integration, onConnect, onClick, size }) => {
  const isConnected = integration.status === "connected";
  const isAvailable = !!integration.loginEndpoint;

  const handleClick = () => {
    onClick(integration.id);
  };

  const handleConnectClick = () => {
    onConnect(integration.id);
  };

  const paddingClass = size === "small" ? "p-2" : "p-4";
  const gapClass = size === "small" ? "gap-2" : "gap-3";

  return (
    <div
      className={`flex min-h-12 cursor-pointer flex-col justify-center ${gapClass} overflow-hidden ${size === "small" ? "rounded-xl" : "rounded-2xl"} bg-zinc-800/40 ${paddingClass} transition hover:bg-zinc-700`}
      onClick={handleClick}
    >
      {/* {color && (
        <div
          className="relative h-30 w-full overflow-hidden rounded-2xl bg-zinc-900"
          // style={{ backgroundColor: color }}
        >
          <div className="flex h-full w-full items-center justify-center">
            <Image
              width={35}
              height={35}
              src={integration.icons[0]}
              alt={integration.name}
              className="z-[3] aspect-square max-w-[70] min-w-[70] rounded-2xl bg-zinc-700/40 object-contain p-3 backdrop-blur-2xl"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />

            <Image
              width={35}
              height={35}
              src={integration.icons[0]}
              alt={integration.name}
              className="absolute top-4 right-7 z-[1] aspect-square max-w-[45] min-w-[45] -rotate-12 object-contain blur-[3px]"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />

            <Image
              width={35}
              height={35}
              src={integration.icons[0]}
              alt={integration.name}
              className="absolute top-6 left-24 z-[1] aspect-square max-w-[20] min-w-[20] -rotate-6 object-contain blur-[4px]"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />

            <Image
              width={35}
              height={35}
              src={integration.icons[0]}
              alt={integration.name}
              className="absolute right-24 bottom-6 z-[1] aspect-square max-w-[25] min-w-[25] -rotate-6 object-contain blur-[5px]"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />

            <Image
              width={35}
              height={35}
              src={integration.icons[0]}
              alt={integration.name}
              className="absolute bottom-4 left-10 z-[1] aspect-square max-w-[35] min-w-[35] rotate-10 object-contain blur-[3px]"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          </div>
        </div>
      )} */}

      <div className="flex items-center gap-3">
        <div className="flex-shrink-0">
          {getToolCategoryIcon(integration.id, {
            size: 22,
            width: 22,
            height: 22,
            showBackground: false,
          })}
        </div>

        {size !== "small" ? (
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="text-sm font-medium">{integration.name}</div>
            <div className="truncate text-xs font-light text-zinc-400">
              {integration.description}
            </div>
          </div>
        ) : (
          <>
            <div className="flex-1 text-sm font-medium">{integration.name}</div>
          </>
        )}

        <div className="flex-shrink-0">
          {isConnected && (
            <Chip size="sm" variant="flat" color="success">
              Connected
            </Chip>
          )}

          {isAvailable && !isConnected && (
            <Button
              size="sm"
              variant="flat"
              color="primary"
              className="text-xs text-primary"
              onPress={handleConnectClick}
            >
              Connect
            </Button>
          )}

          {!isAvailable && (
            <Chip size="sm" variant="flat" color="default" className="text-xs">
              Soon
            </Chip>
          )}
        </div>
      </div>
    </div>
  );
};

export { IntegrationItem };

export const IntegrationsCard: React.FC<IntegrationsCardProps> = ({
  onClose,
  onIntegrationClick,
  size = "default",
}) => {
  const { integrations, connectIntegration } = useIntegrations();

  const { isExpanded, setExpanded } = useIntegrationsAccordion();

  // Convert boolean to Selection for NextUI Accordion
  const selectedKeys = isExpanded ? new Set(["integrations"]) : new Set([]);

  // Handle accordion state changes
  const handleSelectionChange = (keys: Selection) => {
    const expanded =
      keys === "all" || (keys instanceof Set && keys.has("integrations"));
    setExpanded(expanded);
  };

  const handleConnect = async (integrationId: string) => {
    try {
      await connectIntegration(integrationId);
      onClose?.();
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  const connectedCount = integrations.filter(
    (i) => i.status === "connected",
  ).length;

  return (
    <div className="mx-2 mb-3 border-b-1 border-zinc-800">
      <Accordion
        variant="light"
        isCompact
        className="px-0!"
        selectedKeys={selectedKeys}
        onSelectionChange={handleSelectionChange}
        itemClasses={{
          base: "pb-1",
          trigger: "cursor-pointer",
          title: "pl-1",
        }}
      >
        <AccordionItem
          key="integrations"
          textValue={`Integrations ${connectedCount} of ${integrations.length} connected`}
          title={
            <div className="flex items-center gap-3 pt-1">
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-normal text-foreground-500">
                    Integrations
                  </span>
                  <span className="text-xs font-light text-zinc-400">
                    {connectedCount}/{integrations.length}
                  </span>
                </div>
              </div>
            </div>
          }
        >
          <div onClick={(e) => e.stopPropagation()}>
            <div className="grid grid-cols-2 gap-2">
              {integrations.map((integration) => (
                <IntegrationItem
                  key={integration.id}
                  integration={integration}
                  onConnect={handleConnect}
                  size={size}
                  onClick={(id) => onIntegrationClick?.(id)}
                />
              ))}
            </div>
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
};
