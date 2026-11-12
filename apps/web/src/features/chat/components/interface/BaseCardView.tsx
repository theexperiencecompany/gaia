"use client";

import { Button, Dropdown, Header, Tooltip } from "@heroui/react";
import {
  ArrowUpRight01Icon,
  RedoIcon,
  SquareArrowUpRight02Icon,
  ZapIcon,
} from "@icons";
import type React from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { IntegrationConnectCard } from "@/components/shared/IntegrationConnectCard";

export interface CardAction {
  key: string;
  label: string;
  description: string;
  icon?: React.ReactNode;
  onPress?: () => void;
  href?: string;
}

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
  actions?: CardAction[];
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
  actions,
}) => {
  const containerClassName = `flex h-full w-full flex-col ${className} rounded-3xl`;
  const hasMenu = path || (actions && actions.length > 0);
  const hasActions = actions && actions.length > 0;

  return (
    <div className={containerClassName}>
      <div className="flex flex-shrink-0 items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="font-medium text-zinc-300">{title}</h2>
          {onRefresh && isConnected && (
            <Tooltip>
              <Button
                isIconOnly
                size="sm"
                variant="ghost"
                onPress={onRefresh}
                isDisabled={isFetching}
                className="min-w-0 text-zinc-400 transition-colors duration-200 hover:bg-zinc-800"
              >
                <div
                  className={`transition-transform duration-500 ${isFetching ? "animate-spin" : "hover:rotate-180"}`}
                >
                  <RedoIcon className="h-4 w-4" />
                </div>
              </Button>
              <Tooltip.Content placement="bottom" showArrow>
                Refresh
              </Tooltip.Content>
            </Tooltip>
          )}
        </div>
        {hasMenu && (
          <Dropdown className="text-foreground">
            <GaiaButton
              size="sm"
              variant="default-soft"
              className="text-xs text-zinc-400"
            >
              Ask GAIA
              <ArrowUpRight01Icon className="h-3.5 w-3.5" />
            </GaiaButton>
            <Dropdown.Popover placement="bottom end">
              <Dropdown.Menu aria-label={`${title} actions`} className="w-100">
                {hasActions ? (
                  <Dropdown.Section id="ask-gaia">
                    <Header className="px-2 py-1 text-xs text-zinc-500">
                      Ask GAIA
                    </Header>
                    {actions.map((action) => (
                      <Dropdown.Item
                        key={action.key}
                        id={action.key}
                        textValue={action.label}
                        onAction={action.onPress}
                      >
                        {action.icon ?? (
                          <ZapIcon className="size-4 text-default-500" />
                        )}
                        <div className="flex flex-col">
                          <span>{action.label}</span>
                          <span className="whitespace-normal text-xs text-zinc-500">
                            {action.description}
                          </span>
                        </div>
                      </Dropdown.Item>
                    ))}
                  </Dropdown.Section>
                ) : (
                  // Empty fragment needed to satisfy Dropdown.Menu's children type when only path is present
                  <Dropdown.Section id="empty" className="hidden">
                    <Dropdown.Item id="__empty__">{"" as string}</Dropdown.Item>
                  </Dropdown.Section>
                )}
                {path ? (
                  <Dropdown.Section id="navigation">
                    <Header className="px-2 py-1 text-xs text-zinc-500">
                      Navigation
                    </Header>
                    <Dropdown.Item
                      id="view-all"
                      href={path}
                      textValue="View All"
                    >
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-2">
                          <SquareArrowUpRight02Icon className="size-4 text-primary" />
                          View All
                        </div>
                        <span className="whitespace-normal text-xs text-zinc-500">
                          {`Open full ${title.toLowerCase()} page`}
                        </span>
                      </div>
                    </Dropdown.Item>
                  </Dropdown.Section>
                ) : (
                  <Dropdown.Section id="empty2" className="hidden">
                    <Dropdown.Item id="__empty2__">
                      {"" as string}
                    </Dropdown.Item>
                  </Dropdown.Section>
                )}
              </Dropdown.Menu>
            </Dropdown.Popover>
          </Dropdown>
        )}
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
                      variant="tertiary"
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
