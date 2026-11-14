"use client";

import { FieldError, Input, Modal, TextField } from "@heroui/react";
import { useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { LinkButton } from "@/components/shared/LinkButton";
import CopyButton from "@/components/ui/CopyButton";

const E164_PHONE_PATTERN = /^\+[1-9]\d{6,14}$/;

export interface PhoneLinkTarget {
  contactNumber: string;
  command: string;
  actionLink?: string;
}

interface PhoneLinkModalProps {
  isOpen: boolean;
  platformName: string;
  isSubmitting: boolean;
  target: PhoneLinkTarget | null;
  onSubmit: (phone: string) => void;
  onClose: () => void;
}

function CopyableValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl bg-zinc-800 px-3 py-2">
      <div className="min-w-0">
        <p className="text-xs text-zinc-500">{label}</p>
        <p className="truncate font-medium text-sm text-zinc-100">{value}</p>
      </div>
      <CopyButton textToCopy={value} />
    </div>
  );
}

/**
 * The phone-entry branch of the modal. Rendered inside the dialog body, so it
 * unmounts when the modal closes and `phone` starts empty on every open — no
 * reset effect needed.
 */
function PhoneNumberForm({
  platformName,
  isSubmitting,
  onSubmit,
  onClose,
}: Pick<
  PhoneLinkModalProps,
  "platformName" | "isSubmitting" | "onSubmit" | "onClose"
>) {
  const [phone, setPhone] = useState("");
  const isInvalid = phone.length > 0 && !E164_PHONE_PATTERN.test(phone);

  return (
    <>
      <Modal.Header>Your phone number</Modal.Header>
      <Modal.Body>
        <p className="text-sm text-zinc-400">
          {platformName} delivers to registered numbers only, so GAIA needs the
          number you text from.
        </p>
        <TextField isInvalid={isInvalid}>
          <Input
            autoFocus
            type="tel"
            placeholder="+15551234567"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
          <FieldError>Use E.164 format, e.g. +15551234567</FieldError>
        </TextField>
      </Modal.Body>
      <Modal.Footer>
        <GaiaButton variant="default-soft" size="sm" onPress={onClose}>
          Cancel
        </GaiaButton>
        <GaiaButton
          size="sm"
          isPending={isSubmitting}
          isDisabled={!E164_PHONE_PATTERN.test(phone)}
          onPress={() => onSubmit(phone)}
          variant="primary"
        >
          Continue
        </GaiaButton>
      </Modal.Footer>
    </>
  );
}

export function PhoneLinkModal({
  isOpen,
  platformName,
  isSubmitting,
  target,
  onSubmit,
  onClose,
}: PhoneLinkModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Modal.Backdrop>
        <Modal.Container size="sm">
          <Modal.Dialog>
            <Modal.CloseTrigger aria-label="Close" />
            {target ? (
              <>
                <Modal.Header>Text GAIA to finish linking</Modal.Header>
                <Modal.Body className="gap-2">
                  <p className="text-sm text-zinc-400">
                    Send {target.command} to this number from the phone you just
                    registered.
                  </p>
                  <CopyableValue label="Number" value={target.contactNumber} />
                  <CopyableValue label="Send" value={target.command} />
                  {target.actionLink && (
                    <div className="pt-1">
                      <LinkButton
                        href={target.actionLink}
                        target="_blank"
                        rel="noopener noreferrer"
                        variant="default-soft"
                        size="sm"
                      >
                        Open in Messages
                      </LinkButton>
                      <p className="pt-1.5 text-xs text-zinc-500">
                        Opens the Messages app on iPhone and Mac only.
                      </p>
                    </div>
                  )}
                </Modal.Body>
                <Modal.Footer>
                  <GaiaButton size="sm" onPress={onClose} variant="primary">
                    Done
                  </GaiaButton>
                </Modal.Footer>
              </>
            ) : (
              <PhoneNumberForm
                platformName={platformName}
                isSubmitting={isSubmitting}
                onSubmit={onSubmit}
                onClose={onClose}
              />
            )}
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
