import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { CheckCircle } from "lucide-react";
import React from "react";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

import { Integration } from "../types";

interface SpecialIntegrationCardProps {
  integration: Integration;
  isConnected: boolean;
  connectedCount: number;
  totalCount: number;
  onConnect: (id: string) => void;
}

export const SpecialIntegrationCard: React.FC<SpecialIntegrationCardProps> = ({
  integration,
  isConnected,
  connectedCount,
  totalCount,
  onConnect,
}) => {
  const isAvailable = !!integration.loginEndpoint;

  return (
    <div
      className={`group mb-1" } relative mx-0 cursor-pointer rounded-xl border border-transparent outline-0 transition-all duration-150 hover:border-zinc-800 ${
        isAvailable && !isConnected
          ? "hover:bg-zinc-800/50"
          : "hover:bg-zinc-800/20"
      }`}
    >
      <div className={`flex items-center gap-3 p-2 px-3`}>
        {/* Integration Icon */}
        <div className="flex-shrink-0">
          <div className={`flex items-center justify-center rounded-lg`}>
            {integration.includedIntegrations &&
            integration.includedIntegrations.length > 1 ? (
              // Multiple icons in a stacked layout for unified integrations
              <div className="relative flex items-center justify-center -space-x-1">
                {integration.includedIntegrations
                  .slice(0, 4)
                  .map((includedId, index) => (
                    <div
                      key={includedId}
                      className={`aspect-square min-h-8 min-w-8 rounded-md bg-zinc-800 p-1 shadow-medium shadow-zinc-900/80 ${
                        index > 0 ? "-ml-1" : ""
                      } ${
                        index === 0
                          ? "z-30 rotate-6"
                          : index === 1
                            ? "z-20 -rotate-6"
                            : index === 2
                              ? "z-10 rotate-6"
                              : "z-0 -rotate-6"
                      }`}
                    >
                      {getToolCategoryIcon(includedId, {
                        size: 22,
                        width: 22,
                        height: 22,
                        showBackground: false,
                      })}
                    </div>
                  ))}
              </div>
            ) : (
              // Single icon
              getToolCategoryIcon(integration.id, {
                size: 25,
                width: 25,
                height: 25,
                showBackground: false,
              })
            )}
          </div>
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-2">
                <span className={`text-xs font-medium text-white`}>
                  {integration.name}
                </span>
                {isConnected && (
                  <CheckCircle size={12} className="text-green-400" />
                )}
                {!isConnected && connectedCount > 0 && (
                  <span
                    className={`rounded-full bg-orange-500/20 px-2 py-0.5 text-xs text-orange-400`}
                  >
                    {connectedCount}/{totalCount}
                  </span>
                )}
              </div>
              <p className="line-clamp-1 text-xs text-zinc-400">
                {integration.description}
              </p>
            </div>

            {/* Action Buttons */}
            <div className="flex items-center gap-1">
              {isConnected ? (
                <Chip color="success" size="sm">
                  Connected
                </Chip>
              ) : isAvailable ? (
                <Button
                  size="sm"
                  variant="flat"
                  radius="full"
                  color="primary"
                  onPress={() => onConnect(integration.id)}
                >
                  Connect All
                </Button>
              ) : (
                <span
                  className={`rounded bg-zinc-800/50 px-2 py-1 text-xs text-zinc-500`}
                >
                  Soon
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
