import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/react";
import Link from "next/link";
import React from "react";

interface BaseCardViewProps {
  title: string;
  icon: React.ReactNode;
  isLoading: boolean;
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
  path?: string;
}

const BaseCardView: React.FC<BaseCardViewProps> = ({
  title,
  icon,
  isLoading,
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
  path,
}) => {
  const containerClassName = `flex h-full min-h-[40vh] max-h-[40vh] w-full flex-col ${className} rounded-3xl`;

  return (
    <div className={containerClassName}>
      <div className="flex flex-shrink-0 items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="text-lg font-light text-zinc-400">{title}</h3>
        </div>
        {path && (
          <Link href={path}>
            <Button size="sm" color="primary" variant="light">
              View All
            </Button>
          </Link>
        )}
      </div>

      <div className="h-full flex-1">
        <Skeleton
          className="w-full rounded-2xl"
          isLoaded={!isLoading}
          classNames={{ base: "h-full", content: "h-full" }}
        >
          <div className="h-full max-h-[40vh] min-h-[40vh] w-full overflow-y-auto rounded-2xl bg-[#141414]">
            {!isConnected ? (
              <div className="flex h-full flex-col items-center justify-center p-6">
                <div className="mb-4 opacity-50">{icon}</div>
                <p className="mb-4 text-center text-sm text-foreground/60">
                  Connect your account to view {title.toLowerCase()}
                </p>
                {connectIntegrationId && onConnect && (
                  <Button
                    color="primary"
                    variant="flat"
                    size="sm"
                    onPress={() => onConnect(connectIntegrationId)}
                  >
                    {connectButtonText}
                  </Button>
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
        </Skeleton>
      </div>
    </div>
  );
};

export default BaseCardView;
