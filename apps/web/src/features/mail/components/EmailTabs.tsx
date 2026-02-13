"use client";
import { Tab, Tabs } from "@heroui/tabs";

import {
  Cancel01Icon,
  Delete02Icon,
  Mail01Icon,
  MailEdit02Icon,
  SentIcon,
  StarIcon,
} from "@/icons";
import type { MailTab } from "@/types/features/mailTypes";

interface EmailTabsProps {
  activeTab: MailTab;
  onTabChange: (tab: MailTab) => void;
}

const tabs: { key: MailTab; label: string; icon: typeof SentIcon }[] = [
  { key: "inbox", label: "Inbox", icon: Mail01Icon },
  { key: "sent", label: "Sent", icon: SentIcon },
  { key: "starred", label: "Starred", icon: StarIcon },
  { key: "spam", label: "Spam", icon: Cancel01Icon },
  { key: "trash", label: "Trash", icon: Delete02Icon },
  { key: "drafts", label: "Drafts", icon: MailEdit02Icon },
];

export function EmailTabs({ activeTab, onTabChange }: EmailTabsProps) {
  return (
    <div className="border-b border-zinc-800 px-2">
      <Tabs
        aria-label="Mail tabs"
        selectedKey={activeTab}
        onSelectionChange={(key) => onTabChange(key as MailTab)}
        variant="underlined"
        classNames={{
          tabList: "gap-4",
          tab: "h-10",
          cursor: "bg-primary",
        }}
      >
        {tabs.map(({ key, label, icon: Icon }) => (
          <Tab
            key={key}
            title={
              <div className="flex items-center gap-2">
                <Icon size={16} />
                <span>{label}</span>
              </div>
            }
          />
        ))}
      </Tabs>
    </div>
  );
}
