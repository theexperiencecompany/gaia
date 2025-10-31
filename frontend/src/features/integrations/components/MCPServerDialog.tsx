import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import React, { useState } from "react";
import { MCPServerTemplate } from "../api/mcpApi";
import { useIntegrations } from "../hooks/useIntegrations";
import { useMCPServers } from "../hooks/useMCPServers";

interface MCPServerDialogProps {
  isOpen: boolean;
  onClose: () => void;
  template: MCPServerTemplate;
  onSuccess?: () => void;
}

export const MCPServerDialog: React.FC<MCPServerDialogProps> = ({
  isOpen,
  onClose,
  template,
  onSuccess,
}) => {
  const { createServer } = useMCPServers();
  const { integrations, connectIntegration } = useIntegrations();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [serverUrl, setServerUrl] = useState(template.server_url || "");
  const [bearerToken, setBearerToken] = useState("");
  const [apiKey, setApiKey] = useState("");

  // Check if this template uses OAuth
  const usesOAuth = !!template.oauth_integration_id;
  const oauthIntegration = usesOAuth
    ? integrations?.find((i) => i.id === template.oauth_integration_id)
    : null;
  const isOAuthConnected = oauthIntegration?.status === "connected";

  const handleOAuthConnect = () => {
    if (template.oauth_integration_id) {
      connectIntegration(template.oauth_integration_id);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // If OAuth-based and not connected, redirect to OAuth
    if (usesOAuth && !isOAuthConnected) {
      handleOAuthConnect();
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Build mcp-use config format
      const mcpConfig: any = {
        url: serverUrl || template.server_url,
      };

      // Add auth if required
      if (usesOAuth && template.oauth_integration_id) {
        mcpConfig.auth = {
          type: "oauth",
          oauth_integration_id: template.oauth_integration_id,
        };
      } else if (template.requires_auth && bearerToken) {
        mcpConfig.auth = {
          type: "bearer",
          token: bearerToken,
        };
      }

      await createServer({
        server_name: template.id,
        mcp_config: mcpConfig,
        display_name: template.name,
        description: template.description,
        oauth_integration_id: template.oauth_integration_id,
      });

      onSuccess?.();
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to configure MCP server");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="lg">
      <ModalContent>
        <form onSubmit={handleSubmit}>
          <ModalHeader className="flex flex-col gap-1">
            Configure {template.name}
          </ModalHeader>
          <ModalBody>
            <div className="space-y-4">
              <p className="text-sm text-zinc-400">{template.description}</p>

              {/* OAuth Status */}
              {usesOAuth && (
                <div className="rounded-lg bg-zinc-900 p-3">
                  <p className="text-xs font-semibold text-zinc-300">
                    Authentication:
                  </p>
                  <p className="mt-1 text-xs text-zinc-400">
                    {isOAuthConnected
                      ? `✓ Connected to ${oauthIntegration?.name}`
                      : `Connect your ${oauthIntegration?.name || template.oauth_integration_id} account to enable this MCP server`}
                  </p>
                </div>
              )}

              {/* Setup Instructions (only for non-OAuth or when OAuth connected) */}
              {(!usesOAuth || isOAuthConnected) && (
                <div className="rounded-lg bg-zinc-900 p-3">
                  <p className="text-xs font-semibold text-zinc-300">
                    Setup Instructions:
                  </p>
                  <p className="mt-1 text-xs text-zinc-400">
                    {template.setup_instructions}
                  </p>
                  <a
                    href={template.documentation_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-2 inline-block text-xs text-blue-400 hover:text-blue-300"
                  >
                    View Documentation →
                  </a>
                </div>
              )}

              {/* Server URL (if remote and not OAuth or OAuth connected) */}
              {template.server_url && (!usesOAuth || isOAuthConnected) && (
                <Input
                  label="Server URL"
                  placeholder="https://api.example.com"
                  value={serverUrl}
                  onChange={(e) => setServerUrl(e.target.value)}
                  isRequired
                  variant="bordered"
                />
              )}

              {/* Authentication (only for non-OAuth) */}
              {!usesOAuth && template.requires_auth && (
                <Input
                  label={
                    template.auth_type === "bearer"
                      ? "Bearer Token / API Key"
                      : "API Key"
                  }
                  placeholder="Enter your API key or token"
                  value={bearerToken}
                  onChange={(e) => setBearerToken(e.target.value)}
                  isRequired
                  variant="bordered"
                  type="password"
                />
              )}

              {/* Error Display */}
              {error && (
                <div className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">
                  {error}
                </div>
              )}
            </div>
          </ModalBody>
          <ModalFooter>
            <Button
              color="danger"
              variant="light"
              onPress={onClose}
              isDisabled={isLoading}
            >
              Cancel
            </Button>
            <Button
              color="primary"
              type="submit"
              isLoading={isLoading}
              isDisabled={
                isLoading ||
                (!usesOAuth && template.server_url && !serverUrl) ||
                (!usesOAuth && template.requires_auth && !bearerToken)
              }
            >
              {usesOAuth && !isOAuthConnected
                ? `Connect ${oauthIntegration?.name || "OAuth"}`
                : isOAuthConnected
                  ? "Enable MCP Server"
                  : "Configure"}
            </Button>
          </ModalFooter>
        </form>
      </ModalContent>
    </Modal>
  );
};
