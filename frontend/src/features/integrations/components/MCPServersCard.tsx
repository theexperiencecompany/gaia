import { Accordion, AccordionItem } from "@heroui/accordion";
import { Chip } from "@heroui/chip";
import { Modal, ModalContent, ModalHeader, ModalBody } from "@heroui/modal";
import { Selection } from "@heroui/react";
import Image from "next/image";
import React, { useState } from "react";

import { useMCPServers } from "../hooks/useMCPServers";
import { useIntegrations } from "../hooks/useIntegrations";
import { MCPServerTemplate } from "../api/mcpApi";
import { MCPServerDialog } from "./MCPServerDialog";

interface MCPServersCardProps {
  onClose?: () => void;
}

const MCPTemplateItem: React.FC<{
  template: MCPServerTemplate;
  isConfigured: boolean;
  onConfigure: (template: MCPServerTemplate) => void;
}> = ({ template, isConfigured, onConfigure }) => {
  const handleClick = () => {
    if (!isConfigured) {
      onConfigure(template);
    }
  };

  return (
    <div
      className={`flex items-center gap-2 rounded-lg p-2 px-3 transition ${
        !isConfigured ? "cursor-pointer hover:bg-zinc-700/40" : ""
      }`}
      onClick={handleClick}
    >
      {/* Icon */}
      <div className="flex-shrink-0">
        <div className="flex items-center justify-center rounded-lg">
          <Image
            width={25}
            height={25}
            src={template.icon_url}
            alt={template.name}
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
          {template.name}
        </span>
      </div>

      {/* Status / Button */}
      <div className="flex-shrink-0">
        {isConfigured && (
          <Chip size="sm" variant="flat" color="success">
            Connected
          </Chip>
        )}

        {!isConfigured && (
          <Chip size="sm" variant="flat" color="primary" className="text-xs">
            Configure
          </Chip>
        )}
      </div>
    </div>
  );
};

export const MCPServersCard: React.FC<MCPServersCardProps> = ({ onClose }) => {
  const { templates, servers, isLoading, createServer, refreshServers } =
    useMCPServers();
  const { integrations } = useIntegrations();
  const [isExpanded, setExpanded] = useState(false);
  const [selectedTemplate, setSelectedTemplate] =
    useState<MCPServerTemplate | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);

  // Convert boolean to Selection for NextUI Accordion
  const selectedKeys = isExpanded ? new Set(["mcp-servers"]) : new Set([]);

  // Handle accordion state changes
  const handleSelectionChange = (keys: Selection) => {
    const expanded =
      keys === "all" || (keys instanceof Set && keys.has("mcp-servers"));
    setExpanded(expanded);
  };

  const handleConfigure = (template: MCPServerTemplate) => {
    setSelectedTemplate(template);
    setIsDialogOpen(true);
  };

  const handleDialogClose = () => {
    setIsDialogOpen(false);
    setSelectedTemplate(null);
  };

  const handleServerCreated = async () => {
    await refreshServers();
    handleDialogClose();
    onClose?.();
  };

  // Check if a template is already configured
  const isTemplateConfigured = (template: MCPServerTemplate) => {
    // If OAuth-based, check if OAuth integration is connected
    if (template.oauth_integration_id) {
      const oauthIntegration = integrations?.find(
        (i) => i.id === template.oauth_integration_id,
      );
      return oauthIntegration?.connected || false;
    }

    // Otherwise check if server exists
    return servers.some(
      (server) =>
        server.name.toLowerCase().includes(template.id.toLowerCase()) ||
        server.description.toLowerCase().includes(template.id.toLowerCase()),
    );
  };

  const connectedCount = servers.filter((s) => s.enabled).length;

  if (isLoading || templates.length === 0) {
    return null;
  }

  return (
    <>
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
            key="mcp-servers"
            title={
              <div className="flex items-center gap-3 px-1 pt-1">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-normal text-foreground-500">
                      MCP Servers
                    </span>
                    <span className="text-xs font-light text-zinc-400">
                      {connectedCount}/{templates.length}
                    </span>
                  </div>
                </div>
              </div>
            }
          >
            <div onClick={(e) => e.stopPropagation()}>
              <div className="grid grid-cols-2 gap-2">
                {templates.map((template) => (
                  <MCPTemplateItem
                    key={template.id}
                    template={template}
                    isConfigured={isTemplateConfigured(template)}
                    onConfigure={handleConfigure}
                  />
                ))}
              </div>
            </div>
          </AccordionItem>
        </Accordion>
      </div>

      {/* Configuration Dialog */}
      {selectedTemplate && (
        <MCPServerDialog
          isOpen={isDialogOpen}
          onClose={handleDialogClose}
          template={selectedTemplate}
          onSuccess={handleServerCreated}
        />
      )}
    </>
  );
};
