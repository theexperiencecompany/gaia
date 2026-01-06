"use client";

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
import { useState } from "react";
import { toast } from "sonner";

import { ConnectIcon, KeyIcon, PuzzleIcon } from "@/icons";

import { useIntegrations } from "../hooks/useIntegrations";

interface MCPIntegrationModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const MCPIntegrationModal: React.FC<MCPIntegrationModalProps> = ({
  isOpen,
  onClose,
}) => {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const { createCustomIntegration, refetch } = useIntegrations();

  const handleCreate = async () => {
    setIsLoading(true);

    try {
      const result = await createCustomIntegration({
        name,
        description: description.trim() || undefined,
        server_url: serverUrl,
        requires_auth: !!apiKey,
        auth_type: apiKey ? "bearer" : "none",
        is_public: false,
      });

      // Handle auto-connection result
      const connection = result.connection;

      if (connection?.status === "connected") {
        toast.success(
          `Connected to ${result.name} with ${connection.tools_count || 0} tools!`,
        );
        refetch();
        handleClose();
      } else if (connection?.status === "requires_oauth") {
        toast.info("Authorization required - redirecting...");
        refetch();
        handleClose();
        // Redirect to OAuth URL
        if (connection.oauth_url && typeof window !== "undefined") {
          window.location.href = connection.oauth_url;
        }
      } else if (connection?.status === "failed") {
        toast.warning(
          `Integration created, but connection failed: ${connection.error || "Unknown error"}. You can retry from the integrations page.`,
        );
        refetch();
        handleClose();
      } else {
        // Default: just created, no connection attempt
        toast.success("Custom integration created successfully!");
        refetch();
        handleClose();
      }
    } catch (error) {
      console.error("Failed to create custom integration:", error);
      toast.error(
        `Failed to create integration: ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    setName("");
    setDescription("");
    setServerUrl("");
    setApiKey("");
    onClose();
  };

  const isValid = name.trim() !== "" && serverUrl.trim() !== "";

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
              value={name}
              onValueChange={setName}
              isRequired
              startContent={<PuzzleIcon width={16} height={16} />}
            />

            <Textarea
              label="Description"
              placeholder="What does this integration do?"
              value={description}
              onValueChange={setDescription}
              minRows={2}
              maxRows={3}
            />

            <Input
              label="Server URL"
              placeholder="https://mcp.example.com/sse"
              value={serverUrl}
              onValueChange={setServerUrl}
              isRequired
              startContent={<ConnectIcon width={16} height={16} />}
            />

            <Input
              label="API Key (optional)"
              placeholder="sk-..."
              value={apiKey}
              onValueChange={setApiKey}
              type="password"
              description="If provided, API key authentication will be used. Leave empty to automatically detect OAuth requirements."
              startContent={<KeyIcon width={16} height={16} />}
            />
          </div>
        </ModalBody>

        <ModalFooter>
          <Button
            color="default"
            variant="light"
            onPress={handleClose}
            isDisabled={isLoading}
          >
            Cancel
          </Button>
          <Button
            color="primary"
            onPress={handleCreate}
            isLoading={isLoading}
            isDisabled={!isValid || isLoading}
          >
            Create
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};
