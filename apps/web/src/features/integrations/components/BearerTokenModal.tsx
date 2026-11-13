"use client";

import {
  FieldError,
  InputGroup,
  Kbd,
  Label,
  Modal,
  TextField,
} from "@heroui/react";
import { KeyIcon } from "@icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
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

  const handleClose = useCallback(() => {
    if (isLoading) return; // Prevent closing while loading
    setBearerToken("");
    setError(null);
    onClose();
  }, [isLoading, onClose]);

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
  }, [bearerToken, isLoading, integrationId, onSubmit, handleClose]);

  const keyDownStateRef = useRef({ isLoading, isMac, handleSubmit });
  useEffect(() => {
    keyDownStateRef.current = { isLoading, isMac, handleSubmit };
  });

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      const {
        isLoading: loading,
        isMac: mac,
        handleSubmit: submit,
      } = keyDownStateRef.current;
      if (loading) return;
      const modifierKey = mac ? e.metaKey : e.ctrlKey;
      if (modifierKey && e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <Modal.Backdrop
        variant="blur"
        isDismissable={!isLoading}
        isKeyboardDismissDisabled={isLoading}
      >
        <Modal.Container placement="center" size="md">
          <Modal.Dialog className="shadow-none">
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header className="flex flex-col gap-1">
              <Modal.Heading className="text-xl font-semibold">
                Connect {integrationName}
              </Modal.Heading>
              <p className="text-sm font-normal text-zinc-400">
                Enter your API key / Bearer Token to connect
              </p>
            </Modal.Header>

            <Modal.Body>
              <TextField
                name="bearerToken"
                value={bearerToken}
                onChange={setBearerToken}
                type="password"
                isRequired
                isInvalid={!!error}
              >
                <Label>API Key / Bearer Token</Label>
                <InputGroup>
                  <InputGroup.Prefix>
                    <KeyIcon width={16} height={16} />
                  </InputGroup.Prefix>
                  <InputGroup.Input
                    placeholder="sk-... or your token"
                    autoFocus
                  />
                </InputGroup>
                {error && <FieldError>{error}</FieldError>}
              </TextField>
            </Modal.Body>

            <Modal.Footer>
              <GaiaButton
                variant="ghost"
                onPress={handleClose}
                isDisabled={isLoading}
              >
                Cancel
              </GaiaButton>
              <GaiaButton
                onPress={handleSubmit}
                isPending={isLoading}
                isDisabled={!bearerToken.trim() || isLoading}
                variant="primary"
              >
                Connect
                {!isLoading && (
                  <Kbd>
                    <Kbd.Abbr keyValue={modifierKeyName} />
                    <Kbd.Abbr keyValue="enter" />
                  </Kbd>
                )}
              </GaiaButton>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
};
