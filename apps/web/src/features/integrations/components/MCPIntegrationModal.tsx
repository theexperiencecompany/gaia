"use client";

import {
  Button,
  Description,
  InputGroup,
  Kbd,
  Label,
  Modal,
  TextArea,
  TextField,
} from "@heroui/react";
import { ConnectIcon, KeyIcon, PuzzleIcon } from "@icons";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useDeployment } from "@/features/settings/hooks/useSetupStatus";
import { useModalForm } from "@/hooks/ui/useModalForm";
import { useModalKeyboardSubmit } from "@/hooks/ui/useModalKeyboardSubmit";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { toast } from "@/lib/toast";
import { useIntegrations } from "../hooks/useIntegrations";

const SERVER_URL_REGEX = /^https?:\/\/.+/;

interface MCPIntegrationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onIntegrationCreated?: (integrationId: string) => void;
}

interface MCPFormData {
  name: string;
  description: string;
  server_url: string;
  bearer_token: string;
  requires_auth: boolean;
  auth_type: "none" | "oauth" | "bearer";
  is_public: boolean;
  [key: string]: unknown;
}

export const MCPIntegrationModal: React.FC<MCPIntegrationModalProps> = ({
  isOpen,
  onClose,
  onIntegrationCreated,
}) => {
  const { isMac, modifierKeyName } = usePlatform();
  const { createCustomIntegration } = useIntegrations();
  const allowsPrivateServers = useDeployment().private_network_endpoints;

  // Use ref to always get latest callback (avoids stale closure in useModalForm)
  const onIntegrationCreatedRef = useRef(onIntegrationCreated);
  useEffect(() => {
    onIntegrationCreatedRef.current = onIntegrationCreated;
  });

  const initialData = useMemo<MCPFormData>(
    () => ({
      name: "",
      description: "",
      server_url: "",
      bearer_token: "",
      requires_auth: false,
      auth_type: "none",
      is_public: false,
    }),
    [],
  );

  const { formData, loading, handleSubmit, updateField, resetForm } =
    useModalForm<MCPFormData, string>({
      initialData,
      validate: [
        { field: "name", required: true, message: "Name is required" },
        {
          field: "server_url",
          required: true,
          custom: (value) => {
            if (!value || typeof value !== "string")
              return "Server URL is required";
            if (!SERVER_URL_REGEX.test(value)) {
              return "Please enter a valid URL starting with http:// or https://";
            }
            return null;
          },
        },
      ],
      onSubmit: async (data) => {
        const result = await createCustomIntegration({
          name: data.name,
          description: data.description?.trim() || undefined,
          server_url: data.server_url,
          requires_auth: !!data.bearer_token,
          auth_type: data.bearer_token ? "bearer" : "none",
          is_public: false,
          bearer_token: data.bearer_token || undefined,
        });

        // Handle auto-connection result
        const connection = result.connection;

        if (connection?.status === "connected") {
          toast.success(
            `Connected to ${result.name} with ${connection.toolsCount || 0} tools!`,
          );
        } else if (connection?.status === "requires_oauth") {
          toast.info("Authorization required - redirecting...");
          // Redirect to OAuth URL
          if (connection.oauthUrl && typeof window !== "undefined") {
            window.location.href = connection.oauthUrl;
          }
        } else if (connection?.status === "failed") {
          toast.warning(
            `Integration created, but connection failed: ${connection.error || "Unknown error"}. You can retry from the integrations page.`,
          );
        } else {
          toast.success("Custom integration created successfully!");
        }

        // Return the integration ID to be passed to onSuccess
        return result.integrationId;
      },
      onSuccess: (integrationId?: string) => {
        handleClose();
        if (integrationId) {
          onIntegrationCreatedRef.current?.(integrationId);
        }
      },
      resetOnSuccess: true,
    });

  const handleClose = useCallback(() => {
    resetForm();
    onClose();
  }, [resetForm, onClose]);

  useModalKeyboardSubmit({ isOpen, loading, isMac, handleSubmit });

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !loading) handleClose();
      }}
    >
      <Modal.Backdrop isDismissable={!loading}>
        <Modal.Container placement="center" size="lg">
          <Modal.Dialog className="rounded-2xl shadow-none">
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header className="flex flex-col gap-1">
              <Modal.Heading className="text-xl font-semibold">
                New Integration
              </Modal.Heading>
              <p className="text-sm font-normal text-zinc-400">
                Use the Model Context Protocol to extend GAIA&apos;s
                capabilities with external data and tools
              </p>
            </Modal.Header>

            <Modal.Body>
              <div className="flex flex-col gap-4">
                <TextField
                  value={formData.name}
                  onChange={(value) => updateField("name", value)}
                  isRequired
                >
                  <Label>Name</Label>
                  <InputGroup>
                    <InputGroup.Prefix>
                      <PuzzleIcon width={16} height={16} />
                    </InputGroup.Prefix>
                    <InputGroup.Input
                      placeholder="Integration Name"
                      autoFocus
                    />
                  </InputGroup>
                </TextField>

                <TextField
                  value={formData.description || ""}
                  onChange={(value) => updateField("description", value)}
                >
                  <Label>Description</Label>
                  <TextArea
                    placeholder="What does this integration do?"
                    rows={2}
                  />
                </TextField>

                <TextField
                  value={formData.server_url}
                  onChange={(value) => updateField("server_url", value)}
                  isRequired
                >
                  <Label>Server URL</Label>
                  <InputGroup>
                    <InputGroup.Prefix>
                      <ConnectIcon width={16} height={16} />
                    </InputGroup.Prefix>
                    <InputGroup.Input placeholder="https://mcp.example.com/sse" />
                  </InputGroup>
                  {allowsPrivateServers ? (
                    <Description>
                      A server on your network works too. localhost means the
                      machine GAIA runs on.
                    </Description>
                  ) : null}
                </TextField>

                <TextField
                  value={formData.bearer_token || ""}
                  onChange={(value) => updateField("bearer_token", value)}
                >
                  <Label>API Key / Bearer Token (optional)</Label>
                  <InputGroup>
                    <InputGroup.Prefix>
                      <KeyIcon width={16} height={16} />
                    </InputGroup.Prefix>
                    <InputGroup.Input
                      type="password"
                      placeholder="sk-... or your API token"
                    />
                  </InputGroup>
                  <Description>
                    If provided, API key auth will be used. Leave empty for
                    OAuth.
                  </Description>
                </TextField>

                <p className="rounded-2xl bg-zinc-900 p-3 text-xs text-zinc-400">
                  GAIA connects to MCP servers over HTTP (streamable HTTP or
                  SSE). Servers started as a command (stdio) can&apos;t be added
                  here: run one with its HTTP transport or behind an HTTP bridge
                  such as supergateway, or connect it from your computer with
                  the device bridge in Settings, Devices.
                </p>
              </div>
            </Modal.Body>

            <Modal.Footer>
              <Button
                variant="ghost"
                onPress={handleClose}
                isDisabled={loading}
              >
                Cancel
              </Button>
              <Button
                onPress={handleSubmit}
                isPending={loading}
                variant="primary"
              >
                Create
                {!loading && (
                  <Kbd>
                    <Kbd.Abbr keyValue={modifierKeyName} />
                    <Kbd.Abbr keyValue="enter" />
                  </Kbd>
                )}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
};
