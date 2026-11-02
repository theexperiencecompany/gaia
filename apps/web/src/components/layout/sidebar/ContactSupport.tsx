"use client";

import { Button, Tooltip, useOverlayState } from "@heroui/react";
import { BubbleChatQuestionIcon } from "@icons";
import ContactSupportModal from "@/features/support/components/ContactSupportModal";

export default function ContactSupport() {
  const { isOpen, setOpen, open } = useOverlayState();

  return (
    <>
      <div className="flex w-full justify-center">
        <Tooltip>
          <Tooltip.Trigger>
            <Button
              variant="tertiary"
              fullWidth
              className="text-left flex justify-center text-zinc-300 h-7"
              size="sm"
              onPress={open}
            >
              <BubbleChatQuestionIcon width={17} height={17} />
              Contact Support
            </Button>
          </Tooltip.Trigger>
          <Tooltip.Content>
            Need support or want a new feature? Talk to us!
          </Tooltip.Content>
        </Tooltip>
      </div>

      <ContactSupportModal
        isOpen={isOpen}
        onOpenChange={() => setOpen(false)}
      />
    </>
  );
}
