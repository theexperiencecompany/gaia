"use client";

import { Button } from "@heroui/button";
import { useDisclosure } from "@heroui/react";
import { Tooltip } from "@heroui/tooltip";

import { ContactSupportModal } from "@/features/support";
import { BubbleChatQuestionIcon } from "@/icons";

export default function ContactSupport() {
  const { isOpen, onOpen, onOpenChange } = useDisclosure();

  return (
    <>
      <div className="flex w-full justify-center">
        <Tooltip content="Need support or want a new feature? Talk to us!">
          <Button
            variant="flat"
            fullWidth
            className="text-left flex justify-center text-foreground-700 h-7"
            radius="full"
            size="sm"
            startContent={<BubbleChatQuestionIcon width={17} height={17} />}
            onPress={onOpen}
          >
            Contact Support
          </Button>
        </Tooltip>
      </div>

      <ContactSupportModal isOpen={isOpen} onOpenChange={onOpenChange} />
    </>
  );
}
