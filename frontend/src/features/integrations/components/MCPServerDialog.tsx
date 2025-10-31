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

  const handleOAuthConnect = async () => {
    if (!template.oauth_integration_id) {
      setError("OAuth integration ID not configured");
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // First, check if we need to create the MCP server config
      // or if we just need to connect OAuth
      const serverConfig = await createServer({
        server_name: template.id,
        mcp_config: {
          url: template.server_url,
          auth: {
            type: "oauth",
            oauth_integration_id: template.oauth_integration_id,
          },
        },
        display_name: template.name,
        description: template.description,
        oauth_integration_id: template.oauth_integration_id,
      });

      // Now initiate the OAuth flow using the MCP OAuth endpoint
      const response = await fetch(
        `/api/v1/mcp/oauth/${template.id}/authorize`,
        {
          credentials: "include",
        },
      );

      if (!response.ok) {
        throw new Error("Failed to initiate OAuth flow");
      }

      const data = await response.json();
      if (data.authorization_url) {
        // Redirect to OAuth provider
        window.location.href = data.authorization_url;
      } else {
        throw new Error("No authorization URL returned");
      }
    } catch (err: any) {
      // If server already exists, just try to connect OAuth
      if (err.message?.includes("already exists")) {
        try {
          const response = await fetch(
            `/api/v1/mcp/oauth/${template.id}/authorize`,
            {
              credentials: "include",
            },
          );

          if (!response.ok) {
            throw new Error("Failed to initiate OAuth flow");
          }

          const data = await response.json();
          if (data.authorization_url) {
            window.location.href = data.authorization_url;
          } else {
            throw new Error("No authorization URL returned");
          }
        } catch (oauthErr: any) {
          setError(
            oauthErr.message ||
              "Failed to connect OAuth. Please try again.",
          );
          setIsLoading(false);
        }
      } else {
        setError(err.message || "Failed to configure MCP server");
        setIsLoading(false);
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // If OAuth-based and not connected, initiate OAuth flow
    if (usesOAuth && !isOAuthConnected) {
      await handleOAuthConnect();
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
      } else if (template.requires_auth) {
        if (template.auth_type === "bearer" && bearerToken) {
          mcpConfig.auth = {
            type: "bearer",
            token: bearerToken,
          };
        } else if (template.auth_type === "api_key" && apiKey) {
          mcpConfig.auth = {
            type: "api_key",
            key: apiKey,
          };
        }
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
                <>
                  {template.auth_type === "bearer" && (
                    <Input
                      label="Bearer Token"
                      placeholder="Enter your bearer token"
                      value={bearerToken}
                      onChange={(e) => setBearerToken(e.target.value)}
                      isRequired
                      variant="bordered"
                      type="password"
                    />
                  )}
                  {template.auth_type === "api_key" && (
                    <Input
                      label="API Key"
                      placeholder="Enter your API key"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      isRequired
                      variant="bordered"
                      type="password"
                    />
                  )}
                  {!template.auth_type && (
                    <Input
                      label="API Key / Token"
                      placeholder="Enter your API key or token"
                      value={bearerToken}
                      onChange={(e) => setBearerToken(e.target.value)}
                      isRequired
                      variant="bordered"
                      type="password"
                    />
                  )}
                </>
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
                (!usesOAuth &&
                  template.requires_auth &&
                  ((template.auth_type === "bearer" && !bearerToken) ||
                    (template.auth_type === "api_key" && !apiKey) ||
                    (!template.auth_type && !bearerToken)))
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
