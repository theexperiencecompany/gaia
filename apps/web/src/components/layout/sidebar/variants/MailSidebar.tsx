"use client";

import { Button } from "@heroui/react";
import { InboxIcon, QuillWrite01Icon } from "@icons";
import dynamic from "next/dynamic";
import { useState } from "react";

// ssr:false — MailCompose imports @tiptap. Modal-only UI, never visible at
// initial paint, no SEO impact.
const MailCompose = dynamic(
  () => import("@/features/mail/components/MailCompose"),
  { ssr: false },
);

type MailItem = {
  label: string;
  icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
};

const mailItems: MailItem[] = [{ label: "Inbox", icon: InboxIcon }];

type MailButtonProps = {
  label: string;
  Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
};

function MailButton({ label, Icon }: MailButtonProps) {
  return (
    <Button
      variant="tertiary"
      size="sm"
      className="flex w-full justify-start text-sm text-foreground-600"
    >
      <Icon width={21} height={21} />
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
            size="sm"
            className="mx-2 mb-4 flex w-full justify-start text-sm font-medium text-primary"
            onPress={() => setOpen(true)}
            variant="tertiary"
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
