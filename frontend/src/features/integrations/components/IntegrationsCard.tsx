import { Accordion, AccordionItem } from "@heroui/accordion";
import { Chip } from "@heroui/chip";
import { Selection } from "@heroui/react";
import Image from "next/image";
import React, { useEffect } from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useIntegrationsAccordion } from "@/stores/uiStore";

import { Integration } from "../types";
import { SpecialIntegrationCard } from "./SpecialIntegrationCard";

interface IntegrationsCardProps {
  onClose?: () => void;
}

const IntegrationItem: React.FC<{
  integration: Integration;
  onConnect: (id: string) => void;
}> = ({ integration, onConnect }) => {
  const isConnected = integration.status === "connected";
  const isAvailable = !!integration.loginEndpoint;

  const handleClick = () => {
    if (isAvailable && !isConnected) {
      onConnect(integration.id);
    }
  };

  return (
    <div
      className={`flex items-center gap-2 rounded-lg p-2 px-3 transition ${
        isAvailable && !isConnected ? "cursor-pointer hover:bg-zinc-700/40" : ""
      }`}
      onClick={handleClick}
    >
      {/* Icon */}
      <div className="flex-shrink-0">
        <div className="flex items-center justify-center rounded-lg">
          <Image
            width={25}
            height={25}
            src={integration.icons[0]}
            alt={integration.name}
            className="aspect-square max-w-[25px] min-w-[25px] object-contain"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
      </div>

      {/* Name */}
      <div className="min-w-0 flex-1">
        <span className="block truncate text-xs text-zinc-300">
          {integration.name}
        </span>
      </div>

      {/* Status / Button */}
      <div className="flex-shrink-0">
        {isConnected && (
          <Chip size="sm" variant="flat" color="success">
            Connected
          </Chip>
        )}

        {isAvailable && !isConnected && (
          <Chip size="sm" variant="flat" color="primary" className="text-xs">
            Click to Connect
          </Chip>
        )}

        {!isAvailable && (
          <Chip size="sm" variant="flat" color="danger" className="text-xs">
            Soon
          </Chip>
        )}
      </div>
    </div>
  );
};

export const IntegrationsCard: React.FC<IntegrationsCardProps> = ({
  onClose,
}) => {
  const {
    integrations: _integrations,
    connectIntegration,
    refreshStatus,
    getSpecialIntegrations,
    getRegularIntegrations,
    isUnifiedIntegrationConnected,
    getIntegrationStatus,
  } = useIntegrations();

  const { isExpanded, setExpanded } = useIntegrationsAccordion();

  // Convert boolean to Selection for NextUI Accordion
  const selectedKeys = isExpanded ? new Set(["integrations"]) : new Set([]);

  // Handle accordion state changes
  const handleSelectionChange = (keys: Selection) => {
    const expanded =
      keys === "all" || (keys instanceof Set && keys.has("integrations"));
    setExpanded(expanded);
  };

  // Force refresh integration status on mount
  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  const handleConnect = async (integrationId: string) => {
    try {
      await connectIntegration(integrationId);
      onClose?.();
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  // Get special and regular integrations
  const specialIntegrations = getSpecialIntegrations();
  const regularIntegrations = getRegularIntegrations();

  const connectedCount = regularIntegrations.filter(
    (i) => i.status === "connected",
  ).length;

  return (
    <div className="mx-2 mb-3 border-b-1 border-zinc-800">
      <Accordion
        variant="light"
        isCompact
        selectedKeys={selectedKeys}
        onSelectionChange={handleSelectionChange}
        itemClasses={{
          base: "pb-1",
          trigger: "cursor-pointer",
        }}
      >
        <AccordionItem
          key="integrations"
          title={
            <div className="flex items-center gap-3 px-1 pt-1">
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-normal text-foreground-500">
                    Integrations
                  </span>
                  <span className="text-xs font-light text-zinc-400">
                    {connectedCount}/{regularIntegrations.length}
                  </span>
                </div>
              </div>
            </div>
          }
        >
          <div onClick={(e) => e.stopPropagation()}>
            <div>
              {/* Special Integrations (full width) */}
              {specialIntegrations.length > 0 && (
                <div className="mb-3">
                  {specialIntegrations.map((integration) => {
                    const connectedCount =
                      integration.includedIntegrations?.filter(
                        (includedId) =>
                          getIntegrationStatus(includedId)?.connected,
                      ).length || 0;
                    const totalCount =
                      integration.includedIntegrations?.length || 0;
                    const isConnected = isUnifiedIntegrationConnected(
                      integration.id,
                    );

                    return (
                      <div key={integration.id} className="mb-2">
                        <SpecialIntegrationCard
                          integration={integration}
                          isConnected={isConnected}
                          connectedCount={connectedCount}
                          totalCount={totalCount}
                          onConnect={handleConnect}
                        />
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Regular Integrations (2-column grid) */}
              <div className="grid grid-cols-2 gap-2">
                {regularIntegrations.map((integration) => (
                  <IntegrationItem
                    key={integration.id}
                    integration={integration}
                    onConnect={handleConnect}
                  />
                ))}
              </div>
            </div>
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
};
