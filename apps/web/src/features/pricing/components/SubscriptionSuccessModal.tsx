"use client";

import { Button } from "@heroui/button";
import { Modal, ModalContent, ModalFooter, ModalHeader } from "@heroui/modal";
import { ArrowRight01Icon, Tick02Icon } from "@icons";
import { useEffect, useState } from "react";

import UseCreateConfetti from "../../../hooks/ui/useCreateConfetti";

interface SubscriptionSuccessModalProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigateToChat: () => void;
  planName?: string;
  autoRedirectSeconds?: number;
}

export function SubscriptionSuccessModal({
  isOpen,
  onClose,
  onNavigateToChat,
  planName = "Pro",
  autoRedirectSeconds = 3,
}: SubscriptionSuccessModalProps) {
  const [countdown, setCountdown] = useState(autoRedirectSeconds);

  // Trigger confetti animation when modal opens
  useEffect(() => {
    if (isOpen) {
      UseCreateConfetti(3000); // 3 seconds of confetti
      setCountdown(autoRedirectSeconds); // Reset countdown when modal opens
    }
  }, [isOpen, autoRedirectSeconds]);

  // Auto redirect countdown timer
  useEffect(() => {
    if (!isOpen || countdown <= 0) return;

    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          // Redirect when countdown reaches 0
          setTimeout(() => onNavigateToChat(), 100);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [isOpen, countdown, onNavigateToChat]);

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="md" backdrop="blur">
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full">
            <div className="flex aspect-square size-14 items-center justify-center rounded-full bg-primary">
              <Tick02Icon className="size-7 text-white" />
            </div>
          </div>
          <h2 className="text-2xl font-medium">Welcome to {planName}!</h2>
          <p className="text-sm font-light text-foreground-500">
            Your subscription is now active
          </p>
        </ModalHeader>

        <ModalFooter className="flex flex-col gap-2">
          <Button
            color="primary"
            className="w-full font-medium"
            onPress={onNavigateToChat}
            endContent={<ArrowRight01Icon className="h-4 w-4" />}
          >
            {countdown > 0 ? `Let's Chat! (${countdown}s)` : "Let's Chat!"}
          </Button>
          <Button
            variant="light"
            className="w-full text-foreground-400"
            size="sm"
            onPress={onClose}
          >
            I'll explore later
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
