"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import type { IntegrationAccountResponse } from "@shared/api/generated";
import { useState } from "react";

interface IntegrationAccountRenameModalProps {
  /** The account being renamed; null keeps the modal closed. */
  account: IntegrationAccountResponse | null;
  onSave: (accountId: string, nickname: string) => void;
  onClose: () => void;
}

/** Name an account the user's own way; an empty name falls back to its address. */
export function IntegrationAccountRenameModal({
  account,
  onSave,
  onClose,
}: IntegrationAccountRenameModalProps) {
  // Keyed by account in the parent, so this starts fresh for each account.
  const [name, setName] = useState(account?.nickname ?? "");

  const save = () => {
    if (account) onSave(account.id, name.trim());
    onClose();
  };

  return (
    <Modal
      className="text-foreground dark"
      isOpen={account !== null}
      onOpenChange={onClose}
    >
      <ModalContent>
        <ModalHeader className="pb-0">Rename account</ModalHeader>
        <ModalBody>
          <Input
            autoFocus
            aria-label="Account name"
            description={account?.label}
            placeholder={account?.label}
            value={name}
            variant="faded"
            onValueChange={setName}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing) return;
              if (event.key === "Enter") save();
            }}
          />
        </ModalBody>
        <ModalFooter>
          <Button variant="light" onPress={onClose}>
            Cancel
          </Button>
          <Button color="primary" onPress={save}>
            Save
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
