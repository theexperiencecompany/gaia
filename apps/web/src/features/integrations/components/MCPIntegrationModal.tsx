"use client";

import {
  Button,
  Input,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/react";
import { useState } from "react";

interface MCPIntegrationModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const MCPIntegrationModal: React.FC<MCPIntegrationModalProps> = ({
  isOpen,
  onClose,
}) => {
  const [name, setName] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleCreate = async () => {
    setIsLoading(true);

    console.log("Creating MCP Integration:", {
      name,
      serverUrl,
      apiKey: apiKey ? "***" : "(empty)",
    });

    await new Promise((resolve) => setTimeout(resolve, 1000));

    setIsLoading(false);
    handleClose();
  };

  const handleClose = () => {
    setName("");
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
            Use the Model Context Protocol to extend GAIA's capabilities with
            external data and tools
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
            />

            <Input
              label="Server URL"
              placeholder="https://mcp.example.com/sse"
              value={serverUrl}
              onValueChange={setServerUrl}
              isRequired
            />

            <Input
              label="API Key (optional)"
              placeholder="sk-..."
              value={apiKey}
              onValueChange={setApiKey}
              type="password"
              description="If provided, API key authentication will be used. Leave empty to automatically detect OAuth requirements."
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
