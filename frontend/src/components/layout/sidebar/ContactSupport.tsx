"use client";

import { Button } from "@heroui/button";
import { useDisclosure } from "@heroui/react";
import { Tooltip } from "@heroui/tooltip";

import { ContactSupportModal } from "@/features/support";
import { ChatQuestionIcon, QuestionIcon } from "@/icons";

export default function ContactSupport() {
  const { isOpen, onOpen, onOpenChange } = useDisclosure();

  return (
    <>
      <div className="flex w-full justify-center">
        <Tooltip content="Need support or want a new feature? Talk to us!">
          <Button
            variant="flat"
            className="flex h-fit w-full justify-center gap-2 pl-3 text-zinc-300"
            radius="sm"
            onPress={onOpen}
          >
            <ChatQuestionIcon width={20} height={20} />
            <div className="w-full py-2 text-left text-sm text-wrap">
              Need Support?
            </div>
          </Button>
        </Tooltip>
      </div>

      <ContactSupportModal isOpen={isOpen} onOpenChange={onOpenChange} />
    </>
  );
}
