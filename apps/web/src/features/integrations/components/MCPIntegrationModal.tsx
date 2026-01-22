"use client";

import { Kbd } from "@heroui/kbd";
import {
  Button,
  Input,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  Textarea,
} from "@heroui/react";
import { useCallback, useEffect, useMemo } from "react";
import { toast } from "sonner";
import { useModalForm } from "@/hooks/ui/useModalForm";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { ConnectIcon, PuzzleIcon } from "@/icons";
import { useIntegrations } from "../hooks/useIntegrations";

interface MCPIntegrationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onIntegrationCreated?: (integrationId: string) => void;
}

interface MCPFormData {
  name: string;
  description: string;
  server_url: string;
  api_key: string;
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
  const { createCustomIntegration, refetch } = useIntegrations();

  const initialData = useMemo<MCPFormData>(
    () => ({
      name: "",
      description: "",
      server_url: "",
      api_key: "",
      requires_auth: false,
      auth_type: "none",
      is_public: false,
    }),
    [],
  );

  const { formData, loading, handleSubmit, updateField, resetForm } =
    useModalForm<MCPFormData>({
      initialData,
      validate: [
        { field: "name", required: true, message: "Name is required" },
        {
          field: "server_url",
          required: true,
          custom: (value) => {
            if (!value || typeof value !== "string")
              return "Server URL is required";
            if (!/^https?:\/\/.+/.test(value)) {
              return "Please enter a valid URL starting with http:// or https://";
            }
            return null;
          },
        },
      ],
      onSubmit: async (data) => {
        // Auth type is determined by API key presence. OAuth-only integrations
        // are detected by the backend when probing the server URL - the response
        // will indicate requires_oauth status and provide the OAuth redirect URL.
        const result = await createCustomIntegration({
          name: data.name,
          description: data.description?.trim() || undefined,
          server_url: data.server_url,
          requires_auth: !!data.api_key,
          auth_type: data.api_key ? "bearer" : "none",
          is_public: false,
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

        refetch();

        // Return the integration ID to be passed to onSuccess
        return result.integrationId;
      },
      onSuccess: (integrationId?: string) => {
        handleClose();
        // Open the integration sidebar for the newly created integration
        if (integrationId) {
          onIntegrationCreated?.(integrationId);
        }
      },
      resetOnSuccess: true,
    });

  const handleClose = useCallback(() => {
    resetForm();
    onClose();
  }, [resetForm, onClose]);

  // Keyboard shortcut handler for Cmd/Ctrl + Enter to submit
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen || loading) return;

      const modifierKey = isMac ? e.metaKey : e.ctrlKey;
      if (modifierKey && e.key === "Enter") {
        e.preventDefault();
        handleSubmit();
      }
    },
    [isOpen, loading, isMac, handleSubmit],
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [isOpen, handleKeyDown]);

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      placement="center"
      size="lg"
      className="shadow-none rounded-2xl"
      backdrop="blur"
    >
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold">New Integration</h2>
          <p className="text-sm font-normal text-zinc-400">
            Use the Model Context Protocol to extend GAIA&apos;s capabilities
            with external data and tools
          </p>
        </ModalHeader>

        <ModalBody>
          <div className="flex flex-col gap-4">
            <Input
              label="Name"
              placeholder="Integration Name"
              value={formData.name}
              onValueChange={(v) => updateField("name", v)}
              isRequired
              startContent={<PuzzleIcon width={16} height={16} />}
              autoFocus
            />

            <Textarea
              label="Description"
              placeholder="What does this integration do?"
              value={formData.description || ""}
              onValueChange={(v) => updateField("description", v)}
              minRows={2}
              maxRows={3}
            />

            <Input
              label="Server URL"
              placeholder="https://mcp.example.com/sse"
              value={formData.server_url}
              onValueChange={(v) => updateField("server_url", v)}
              isRequired
              startContent={<ConnectIcon width={16} height={16} />}
            />

            {/* <Input
              label="API Key (optional)"
              placeholder="sk-..."
              value={formData.api_key || ""}
              onValueChange={(v) => updateField("api_key", v)}
              type="password"
              description="If provided, API key authentication will be used. Leave empty to automatically detect OAuth requirements."
              startContent={<KeyIcon width={16} height={16} />}
            /> */}
          </div>
        </ModalBody>

        <ModalFooter>
          <Button
            color="default"
            variant="light"
            onPress={handleClose}
            isDisabled={loading}
          >
            Cancel
          </Button>
          <Button
            color="primary"
            onPress={handleSubmit}
            isLoading={loading}
            endContent={!loading && <Kbd keys={[modifierKeyName, "enter"]} />}
          >
            Create
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};
