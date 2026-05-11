"use client";

import { useState } from "react";

interface ConfirmationOptions {
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "destructive";
}

interface ConfirmationState extends ConfirmationOptions {
  isOpen: boolean;
  resolve?: (confirmed: boolean) => void;
}

export function useConfirmation() {
  const [confirmationState, setConfirmationState] = useState<ConfirmationState>(
    {
      isOpen: false,
      message: "",
    },
  );

  const confirm = (options: ConfirmationOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      setConfirmationState({
        ...options,
        isOpen: true,
        resolve,
      });
    });
  };

  const handleConfirm = () => {
    confirmationState.resolve?.(true);
    setConfirmationState((prev) => ({ ...prev, isOpen: false }));
  };

  const handleCancel = () => {
    confirmationState.resolve?.(false);
    setConfirmationState((prev) => ({ ...prev, isOpen: false }));
  };

  return {
    confirm,
    confirmationProps: {
      isOpen: confirmationState.isOpen,
      title: confirmationState.title,
      message: confirmationState.message,
      confirmText: confirmationState.confirmText,
      cancelText: confirmationState.cancelText,
      variant: confirmationState.variant,
      onConfirm: handleConfirm,
      onCancel: handleCancel,
    },
  };
}
