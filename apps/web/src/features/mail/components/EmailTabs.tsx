"use client";
import { Chip } from "@heroui/chip";
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
  unreadCounts?: Partial<Record<MailTab, number>>;
}

const tabs: { key: MailTab; label: string; icon: typeof SentIcon }[] = [
  { key: "inbox", label: "Inbox", icon: Mail01Icon },
  { key: "sent", label: "Sent", icon: SentIcon },
  { key: "starred", label: "Starred", icon: StarIcon },
  { key: "spam", label: "Spam", icon: Cancel01Icon },
  { key: "trash", label: "Trash", icon: Delete02Icon },
  { key: "drafts", label: "Drafts", icon: MailEdit02Icon },
];

export function EmailTabs({
  activeTab,
  onTabChange,
  unreadCounts,
}: EmailTabsProps) {
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
        {tabs.map(({ key, label, icon: Icon }) => {
          const count = unreadCounts?.[key];
          return (
            <Tab
              key={key}
              title={
                <div className="flex items-center gap-2">
                  <Icon size={16} />
                  <span>{label}</span>
                  {count != null && count > 0 && (
                    <Chip
                      size="sm"
                      color="primary"
                      variant="flat"
                    >
                      {count > 99 ? "99+" : count}
                    </Chip>
                  )}
                </div>
              }
            />
          );
        })}
      </Tabs>
    </div>
  );
}
