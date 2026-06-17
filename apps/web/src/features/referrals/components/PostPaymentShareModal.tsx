"use client";

import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { GiftIcon } from "@icons";
import { useReferralOverview } from "../hooks/useReferrals";
import { ShareZone } from "./ShareZone";

interface PostPaymentShareModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Fires right after a successful subscription — the highest-converting moment to
 * ask for a referral. Shows the share link + channels; a friend who subscribes
 * earns the new PRO user a free month.
 */
export function PostPaymentShareModal({
  isOpen,
  onClose,
}: PostPaymentShareModalProps) {
  const { data: overview } = useReferralOverview();

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="md"
      placement="center"
      backdrop="blur"
      classNames={{ base: "bg-zinc-900", closeButton: "text-zinc-500" }}
    >
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1 pb-1">
          <span className="flex size-10 items-center justify-center rounded-xl bg-primary/15 text-primary">
            <GiftIcon width={20} height={20} />
          </span>
          <h2 className="mt-2 text-xl font-medium text-white">
            Welcome to GAIA Pro
          </h2>
          <p className="text-sm font-light text-zinc-400">
            Know someone who'd love this? Give them a month of Pro, and earn a
            free month yourself when they subscribe.
          </p>
        </ModalHeader>
        <ModalBody>
          {overview && (
            <ShareZone shareLink={overview.share_link} code={overview.code} />
          )}
        </ModalBody>
        <ModalFooter>
          <Button
            variant="light"
            className="rounded-xl text-zinc-400"
            onPress={onClose}
          >
            Maybe later
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
