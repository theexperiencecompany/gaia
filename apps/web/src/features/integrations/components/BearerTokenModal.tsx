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
import { KeyIcon } from "@/icons";

interface BearerTokenModalProps {
  isOpen: boolean;
  onClose: () => void;
  integrationId: string;
  integrationName: string;
  onSubmit: (integrationId: string, bearerToken: string) => Promise<void>;
}

export const BearerTokenModal: React.FC<BearerTokenModalProps> = ({
  isOpen,
  onClose,
  integrationId,
  integrationName,
  onSubmit,
}) => {
  const [bearerToken, setBearerToken] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!bearerToken.trim()) return;

    setIsLoading(true);
    setError(null);

    try {
      await onSubmit(integrationId, bearerToken);
      handleClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    setBearerToken("");
    setError(null);
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      placement="center"
      size="md"
      className="shadow-none rounded-2xl"
      backdrop="blur"
    >
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold">Connect {integrationName}</h2>
          <p className="text-sm font-normal text-zinc-400">
            Enter your API key or bearer token to connect
          </p>
        </ModalHeader>

        <ModalBody>
          <Input
            label="API Key / Bearer Token"
            placeholder="sk-... or your token"
            value={bearerToken}
            onValueChange={setBearerToken}
            type="password"
            isRequired
            startContent={<KeyIcon width={16} height={16} />}
            errorMessage={error}
            isInvalid={!!error}
          />
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
            onPress={handleSubmit}
            isLoading={isLoading}
            isDisabled={!bearerToken.trim() || isLoading}
          >
            Connect
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};
