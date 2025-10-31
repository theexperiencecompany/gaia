import {
  Modal,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
} from "@heroui/modal";
import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import React, { useState } from "react";
import { MCPServerTemplate } from "../api/mcpApi";
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
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [serverUrl, setServerUrl] = useState(template.server_url || "");
  const [bearerToken, setBearerToken] = useState("");
  const [apiKey, setApiKey] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      const authConfig: any = {
        auth_type: template.requires_auth
          ? template.auth_type || "bearer"
          : "none",
      };

      if (template.requires_auth && bearerToken) {
        if (template.auth_type === "bearer") {
          authConfig.bearer_token = bearerToken;
        } else if (template.auth_type === "basic") {
          authConfig.bearer_token = bearerToken; // Can be enhanced for username/password
        }
      }

      await createServer({
        name: template.name,
        description: template.description,
        server_type: template.server_url ? "http" : "stdio",
        enabled: true,
        http_config: template.server_url
          ? {
              url: serverUrl,
              timeout: 30,
            }
          : undefined,
        auth_config: authConfig,
      });

      onSuccess?.();
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

              {/* Setup Instructions */}
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

              {/* Server URL (if remote) */}
              {template.server_url && (
                <Input
                  label="Server URL"
                  placeholder="https://api.example.com"
                  value={serverUrl}
                  onChange={(e) => setServerUrl(e.target.value)}
                  isRequired
                  variant="bordered"
                />
              )}

              {/* Authentication */}
              {template.requires_auth && (
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
                (template.server_url && !serverUrl) ||
                (template.requires_auth && !bearerToken)
              }
            >
              Configure
            </Button>
          </ModalFooter>
        </form>
      </ModalContent>
    </Modal>
  );
};
