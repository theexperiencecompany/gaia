"use client";

import { Button, Description, Input, Modal, TextField } from "@heroui/react";
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
    <Modal>
      <Modal.Backdrop
        isOpen={account !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) onClose();
        }}
      >
        <Modal.Container>
          <Modal.Dialog className="text-foreground dark">
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header className="pb-0">Rename account</Modal.Header>
            <Modal.Body>
              <TextField value={name} onChange={setName}>
                <Input
                  autoFocus
                  aria-label="Account name"
                  placeholder={account?.label}
                  onKeyDown={(event) => {
                    if (event.nativeEvent.isComposing) return;
                    if (event.key === "Enter") save();
                  }}
                />
                {account?.label ? (
                  <Description>{account.label}</Description>
                ) : null}
              </TextField>
            </Modal.Body>
            <Modal.Footer>
              <Button variant="tertiary" onPress={onClose}>
                Cancel
              </Button>
              <Button onPress={save} variant="primary">
                Save
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
