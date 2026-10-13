import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { RedoIcon } from "@icons";
import {
  CONNECT_ACTION_LABEL,
  formatRelativeTime,
  integrationConnectionState,
} from "@shared/utils";
import type React from "react";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import type { Integration } from "../types";

const IntegrationRow: React.FC<{
  integration: Integration;
  onConnect: (id: string) => void;
  onClick: (id: string) => void;
}> = ({ integration, onConnect, onClick }) => {
  const state = integrationConnectionState(integration.status);
  const isConnected = state === "connected";
  // Custom integrations are always available, platform integrations use available field
  const isAvailable = integration.source === "custom" || integration.available;
  const needsAttention = state === "pending" || state === "expired";
  // How long the grant has been dead — the difference between "I never set this
  // up" and "this broke while I wasn't looking".
  const disconnectedAgo =
    state === "expired" && integration.expiredAt
      ? formatRelativeTime(integration.expiredAt)
      : null;

  const handleClick = () => {
    onClick(integration.id);
  };

  return (
    <div className="flex min-h-16 items-center gap-4 overflow-hidden rounded-2xl bg-zinc-800/0 px-4 py-3 hover:bg-zinc-800 transition-colors duration-200">
      <button
        type="button"
        className="flex min-w-0 flex-1 cursor-pointer items-center gap-4 text-left"
        onClick={handleClick}
      >
        <div className="shrink-0">
          <IntegrationIcon
            integrationId={integration.id}
            iconUrl={integration.iconUrl}
            category={integration.category}
            size={32}
          />
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="font-medium">{integration.name}</div>
          <div className="flex min-w-0 items-center gap-2">
            <div className="truncate text-sm font-light text-zinc-400">
              {integration.description}
            </div>
            {disconnectedAgo && (
              <span className="shrink-0 text-xs text-zinc-500">
                Disconnected {disconnectedAgo}
              </span>
            )}
          </div>
        </div>
      </button>

      <div className="shrink-0">
        {isConnected && (
          <Chip size="sm" variant="flat" color="success">
            Connected
          </Chip>
        )}

        {(isAvailable || needsAttention) && !isConnected && (
          <Button
            variant="flat"
            size="sm"
            color={needsAttention ? "warning" : "primary"}
            startContent={
              needsAttention ? <RedoIcon width={16} height={16} /> : undefined
            }
            onPress={() => {
              onConnect(integration.id);
            }}
          >
            {CONNECT_ACTION_LABEL[state]}
          </Button>
        )}
      </div>
    </div>
  );
};

interface IntegrationSectionProps {
  title: string;
  integrations: Integration[];
  chipColor?: "primary" | "default";
  onConnect: (id: string) => void;
  onIntegrationClick?: (id: string) => void;
}

export const IntegrationSection: React.FC<IntegrationSectionProps> = ({
  title,
  integrations,
  chipColor = "default",
  onConnect,
  onIntegrationClick,
}) => {
  if (integrations.length === 0) return null;

  return (
    <div className="mb-8">
      <div className="mb-4 flex items-center gap-3 pl-4">
        <h2 className="text-base font-semibold">{title}</h2>
        <Chip size="sm" variant="flat" color={chipColor}>
          {integrations.length}
        </Chip>
      </div>
      <div className="flex flex-col gap-2">
        {integrations.map((integration) => (
          <IntegrationRow
            key={integration.id}
            integration={integration}
            onConnect={onConnect}
            onClick={(id) => onIntegrationClick?.(id)}
          />
        ))}
      </div>
    </div>
  );
};
