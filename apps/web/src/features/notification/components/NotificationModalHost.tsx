"use client";

import { EmailPreviewModal } from "@/features/mail/components/EmailPreviewModal";
import type {
  ModalConfig,
  ModalProps,
} from "@/types/features/notificationTypes";

interface NotificationModalHostProps {
  config: ModalConfig | null;
  onClose: () => void;
  onEmailSent?: () => void;
}

/** Renders the modal a notification's modal action asked for. */
export function NotificationModalHost({
  config,
  onClose,
  onEmailSent,
}: NotificationModalHostProps) {
  if (config?.component !== "EmailPreviewModal") return null;
  // `props` is untyped on the wire; the component name is what makes it an EmailPreview payload.
  const props = config.props as ModalProps | undefined;
  if (!props) return null;

  return (
    <EmailPreviewModal
      isOpen={true}
      onClose={onClose}
      subject={props.subject || ""}
      body={props.body || ""}
      recipients={props.recipients || []}
      mode={props.mode === "view" ? "view" : "edit"}
      onEmailSent={onEmailSent}
      notificationId={props.notificationId}
      actionId={props.actionId}
    />
  );
}
