"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Link } from "@heroui/link";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { useState } from "react";
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
 * The phone-entry branch of the modal. Rendered inside `<ModalContent>`, so it
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

  return (
    <>
      <ModalHeader>Your phone number</ModalHeader>
      <ModalBody>
        <p className="text-sm text-zinc-400">
          {platformName} delivers to registered numbers only, so GAIA needs the
          number you text from.
        </p>
        <Input
          autoFocus
          type="tel"
          placeholder="+15551234567"
          value={phone}
          onValueChange={setPhone}
          isInvalid={phone.length > 0 && !E164_PHONE_PATTERN.test(phone)}
          errorMessage="Use E.164 format, e.g. +15551234567"
        />
      </ModalBody>
      <ModalFooter>
        <Button variant="flat" size="sm" onPress={onClose}>
          Cancel
        </Button>
        <Button
          color="primary"
          size="sm"
          isLoading={isSubmitting}
          isDisabled={!E164_PHONE_PATTERN.test(phone)}
          onPress={() => onSubmit(phone)}
        >
          Continue
        </Button>
      </ModalFooter>
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
    <Modal isOpen={isOpen} onClose={onClose} size="sm">
      <ModalContent>
        {target ? (
          <>
            <ModalHeader>Text GAIA to finish linking</ModalHeader>
            <ModalBody className="gap-2">
              <p className="text-sm text-zinc-400">
                Send {target.command} to this number from the phone you just
                registered.
              </p>
              <CopyableValue label="Number" value={target.contactNumber} />
              <CopyableValue label="Send" value={target.command} />
              {target.actionLink && (
                <div className="pt-1">
                  <Button
                    as={Link}
                    href={target.actionLink}
                    isExternal
                    variant="flat"
                    size="sm"
                  >
                    Open in Messages
                  </Button>
                  <p className="pt-1.5 text-xs text-zinc-500">
                    Opens the Messages app on iPhone and Mac only.
                  </p>
                </div>
              )}
            </ModalBody>
            <ModalFooter>
              <Button color="primary" size="sm" onPress={onClose}>
                Done
              </Button>
            </ModalFooter>
          </>
        ) : (
          <PhoneNumberForm
            platformName={platformName}
            isSubmitting={isSubmitting}
            onSubmit={onSubmit}
            onClose={onClose}
          />
        )}
      </ModalContent>
    </Modal>
  );
}
