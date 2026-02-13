"use client";

import { Button } from "@heroui/button";
import { InboxIcon, QuillWrite01Icon } from "@icons";
import { useState } from "react";
import MailCompose from "@/features/mail/components/MailCompose";

type MailItem = {
  label: string;
  icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
};

const mailItems: MailItem[] = [
  { label: "Inbox", icon: InboxIcon },
  // { label: "Important", icon: LabelImportantIcon },
  // { label: "Sent", icon: Sent02Icon },
  // { label: "Drafts", icon: LicenseDraftIcon },
  // { label: "Scheduled", icon: TimeScheduleIcon },
  //   { label: "Trash", icon: LicenseDraftIcon },
];

type MailButtonProps = {
  label: string;
  Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
};

function MailButton({ label, Icon }: MailButtonProps) {
  return (
    <Button
      startContent={<Icon width={21} height={21} />}
      variant="light"
      radius="sm"
      size="sm"
      className="flex w-full justify-start text-sm text-foreground-600"
    >
      {label}
    </Button>
  );
}

type MailContainerProps = {
  items: MailItem[];
};

function MailContainer({ items }: MailContainerProps) {
  return (
    <div className="flex h-full flex-col">
      {items.map((item) => (
        <MailButton key={item.label} label={item.label} Icon={item.icon} />
      ))}
    </div>
  );
}

export default function EmailSidebar() {
  const [open, setOpen] = useState<boolean>(false);

  return (
    <>
      <div className="flex h-full flex-col gap-1">
        <div className="flex w-full justify-center">
          <Button
            color="primary"
            size="sm"
            className="mx-2 mb-4 flex w-full justify-start text-sm font-medium text-primary"
            onPress={() => setOpen(true)}
            variant="flat"
          >
            <QuillWrite01Icon width={18} height={18} />
            Compose Email
          </Button>
        </div>
        <MailContainer items={mailItems} />
      </div>
      <MailCompose open={open} onOpenChange={setOpen} />
    </>
  );
}
