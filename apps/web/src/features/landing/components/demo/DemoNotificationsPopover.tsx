"use client";

import { Button } from "@heroui/button";
import { ScrollArea } from "@radix-ui/react-scroll-area";
import { AnimatePresence, m } from "motion/react";
import { useState } from "react";

import { CheckmarkBadge01Icon } from "@/icons";
import { DUMMY_NOTIFICATIONS, ease } from "./demoConstants";

interface DemoNotificationsPopoverProps {
  open: boolean;
  onClose: () => void;
}

// Mirrors real NotificationCenter — Tabs (Unread/All) + NotificationItem styling
export default function DemoNotificationsPopover({
  open,
  onClose,
}: DemoNotificationsPopoverProps) {
  const [activeTab, setActiveTab] = useState<"unread" | "all">("unread");
  const unreadNotifications = DUMMY_NOTIFICATIONS.filter((n) => n.unread);
  const shown =
    activeTab === "unread" ? unreadNotifications : DUMMY_NOTIFICATIONS;

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Click-outside backdrop */}
          <div
            className="fixed inset-0 z-[150]"
            onClick={onClose}
            onKeyDown={(e) => e.key === "Escape" && onClose()}
          />

          <m.div
            initial={{ opacity: 0, y: -8, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.96 }}
            transition={{ duration: 0.15, ease }}
            className="absolute right-2 top-12 z-[200] w-96 overflow-hidden rounded-2xl border border-zinc-700 bg-zinc-800 p-0 shadow-xl"
          >
            {/* Tabs — mirrors HeroUI Tabs underlined */}
            <div className="flex w-full border-b border-zinc-700">
              {(["unread", "all"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setActiveTab(tab)}
                  className={`flex flex-1 items-center justify-center gap-2 px-4 py-3 text-sm transition-colors ${
                    activeTab === tab
                      ? "border-b-2 border-primary text-white"
                      : "text-zinc-400 hover:text-zinc-300"
                  }`}
                >
                  <span className="capitalize">{tab}</span>
                  {tab === "unread" && unreadNotifications.length > 0 && (
                    <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[10px] font-medium text-zinc-950">
                      {unreadNotifications.length}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* Notification list — exact NotificationItem styling */}
            <ScrollArea className="h-[50vh] w-full">
              <div className="w-full space-y-2 p-3">
                {shown.map((n) => (
                  <div
                    key={n.id}
                    className="w-full rounded-2xl bg-zinc-900 p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <h4 className="max-w-[250px] truncate text-sm font-medium text-zinc-100">
                            {n.title}
                          </h4>
                          {n.unread && (
                            <div className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                          )}
                        </div>
                        <p className="my-1 line-clamp-2 text-left text-sm font-light text-zinc-400">
                          {n.body}
                        </p>
                        <div className="mt-1 flex items-center gap-2 text-xs text-zinc-600">
                          <span>{n.time}</span>
                          <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs capitalize text-zinc-400">
                            {n.tag}
                          </span>
                        </div>
                      </div>
                      {n.unread && (
                        <div className="flex shrink-0 items-center gap-1">
                          <Button
                            variant="flat"
                            size="sm"
                            isIconOnly
                            title="Mark as read"
                          >
                            <CheckmarkBadge01Icon className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>

            {/* Footer */}
            <div className="flex w-full items-center justify-evenly gap-3 p-3">
              <Button size="sm" fullWidth>
                Mark all as read
              </Button>
              <Button size="sm" variant="bordered" fullWidth>
                View all notifications
              </Button>
            </div>
          </m.div>
        </>
      )}
    </AnimatePresence>
  );
}
