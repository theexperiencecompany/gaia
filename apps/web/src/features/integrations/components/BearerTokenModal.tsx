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
} from "@heroui/react";
import { KeyIcon } from "@icons";
import { useCallback, useEffect, useState } from "react";
import { usePlatform } from "@/hooks/ui/usePlatform";

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
  const { isMac, modifierKeyName } = usePlatform();
  const [bearerToken, setBearerToken] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(async () => {
    if (!bearerToken.trim() || isLoading) return;

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
  }, [bearerToken, isLoading, integrationId, onSubmit]);

  const handleClose = () => {
    if (isLoading) return; // Prevent closing while loading
    setBearerToken("");
    setError(null);
    onClose();
  };

  // Keyboard shortcut handler for Cmd/Ctrl + Enter to submit
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen || isLoading) return;

      const modifierKey = isMac ? e.metaKey : e.ctrlKey;
      if (modifierKey && e.key === "Enter") {
        e.preventDefault();
        handleSubmit();
      }
    },
    [isOpen, isLoading, isMac, handleSubmit],
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
      size="md"
      className="shadow-none rounded-2xl"
      backdrop="blur"
      isDismissable={!isLoading}
      isKeyboardDismissDisabled={isLoading}
    >
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold">Connect {integrationName}</h2>
          <p className="text-sm font-normal text-zinc-400">
            Enter your API key / Bearer Token to connect
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
            autoFocus
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
            endContent={!isLoading && <Kbd keys={[modifierKeyName, "enter"]} />}
          >
            Connect
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};
