import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import Link from "next/link";
import type React from "react";

import { IntegrationConnectCard } from "@/components/shared/IntegrationConnectCard";
import { RedoIcon } from "@/icons";

interface BaseCardViewProps {
  title: string;
  icon: React.ReactNode;
  isFetching?: boolean;
  error?: string | null;
  isEmpty?: boolean;
  emptyMessage?: string;
  errorMessage?: string;
  children: React.ReactNode;
  className?: string;
  // Connection state props
  isConnected?: boolean;
  connectIntegrationId?: string;
  onConnect?: (integrationId: string) => void;
  connectButtonText?: string;
  connectTitle?: string;
  connectDescription?: string;
  connectIcon?: React.ReactNode;
  path?: string;
  onRefresh?: () => void;
}

const BaseCardView: React.FC<BaseCardViewProps> = ({
  title,
  icon,
  isFetching = false,
  error,
  isEmpty = false,
  emptyMessage = "No data available",
  errorMessage = "Failed to load data",
  children,
  className = "",
  // Connection state props
  isConnected = true,
  connectIntegrationId,
  onConnect,
  connectButtonText = "Connect",
  connectTitle,
  connectDescription,
  connectIcon,
  path,
  onRefresh,
}) => {
  const containerClassName = `flex h-full min-h-[40vh] max-h-[40vh] w-full flex-col ${className} rounded-3xl`;

  return (
    <div className={containerClassName}>
      <div className="flex flex-shrink-0 items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="font-medium text-zinc-300">{title}</h3>
          {onRefresh && isConnected && (
            <Tooltip content="Refresh" showArrow placement="bottom">
              <Button
                isIconOnly
                size="sm"
                variant="light"
                onPress={onRefresh}
                isDisabled={isFetching}
                className="min-w-0 text-zinc-400 transition-all duration-200 hover:bg-zinc-800"
              >
                <RedoIcon
                  className={`h-4 w-4 transition-transform duration-500 ${isFetching ? "animate-spin" : "hover:rotate-180"}`}
                />
              </Button>
            </Tooltip>
          )}
        </div>
        <div className="flex items-center gap-1">
          {path && (
            <Link href={path}>
              <Button size="sm" color="primary" variant="light">
                View All
              </Button>
            </Link>
          )}
        </div>
      </div>

      <div className="h-full flex-1 px-4 pb-4">
        <div className="h-full max-h-[40vh] min-h-[40vh] w-full overflow-y-auto rounded-2xl bg-secondary-bg">
          {!isConnected ? (
            <div className="flex h-full flex-col items-center justify-center p-6">
              {connectIntegrationId ? (
                <IntegrationConnectCard
                  icon={connectIcon || icon}
                  title={connectTitle || `Connect ${title}`}
                  description={connectDescription || `Connect`}
                  buttonText={connectButtonText}
                  integrationId={connectIntegrationId}
                />
              ) : (
                <>
                  <div className="mb-4 opacity-50">{icon}</div>
                  <p className="mb-4 text-center text-sm text-foreground/60">
                    Connect your account to view {title.toLowerCase()}
                  </p>
                  {onConnect && (
                    <Button
                      color="primary"
                      variant="flat"
                      size="sm"
                      onPress={() => onConnect(connectIntegrationId || "")}
                    >
                      {connectButtonText}
                    </Button>
                  )}
                </>
              )}
            </div>
          ) : error || isEmpty ? (
            <div className="flex h-full flex-col items-center justify-center">
              <div className="mb-2 opacity-50">{icon}</div>
              <p className="text-sm text-foreground/60">
                {error ? errorMessage : emptyMessage}
              </p>
            </div>
          ) : (
            children
          )}
        </div>
      </div>
    </div>
  );
};

export default BaseCardView;
