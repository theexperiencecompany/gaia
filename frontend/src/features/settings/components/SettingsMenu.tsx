"use client";

import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { CircleArrowUp } from "lucide-react";
import { useRouter } from "next/navigation";
import React, { ReactNode, useState } from "react";

import {
  Brain02Icon,
  DiscordIcon,
  Settings01Icon,
  ThreeDotsMenu,
  WhatsappIcon,
} from "@/components/shared/icons";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { getLinkByLabel } from "@/config/appConfig";
import { useLogout } from "@/features/auth/hooks/useLogout";
import { chatApi } from "@/features/chat/api/chatApi";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useFetchConversations } from "@/features/chat/hooks/useConversationList";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import { ContactSupportModal } from "@/features/support";
import { useConfirmation } from "@/hooks/useConfirmation";
import { useConversationsStore } from "@/stores/conversationsStore";

// Only allow these values in our modal state.
export type ModalAction = "clear_chats" | "logout";

interface MenuItem {
  key: string;
  label: React.ReactNode;
  color?: "danger";
  action?: () => void;
}

export default function SettingsMenu({
  children = (
    <Button isIconOnly aria-label="Three Dots Menu" variant="light">
      <ThreeDotsMenu />
    </Button>
  ),
}: {
  children?: ReactNode;
}) {
  const router = useRouter();
  const { clearConversations } = useConversationsStore();
  const fetchConversations = useFetchConversations();
  const { updateConvoMessages } = useConversation();
  const { logout } = useLogout();
  const { confirm, confirmationProps } = useConfirmation();

  const discordLink = getLinkByLabel("Discord");
  const whatsappLink = getLinkByLabel("WhatsApp");
  const [supportModalOpen, setSupportModalOpen] = useState(false);
  const { data: subscriptionStatus } = useUserSubscriptionStatus();

  // Confirm logout action.
  const handleConfirmLogout = async () => {
    const confirmed = await confirm({
      title: "Confirm Logout",
      message: "Are you sure you want to logout?",
      confirmText: "Logout",
      cancelText: "Cancel",
      variant: "destructive",
    });

    if (!confirmed) return;

    try {
      await logout();
    } catch (error) {
      console.error("Error during logout:", error);
    }
  };

  // Confirm clear chats action.
  const handleConfirmClearChats = async () => {
    const confirmed = await confirm({
      title: "Clear All Chats",
      message: "Are you sure you want to delete all chats?",
      confirmText: "Delete all chats",
      cancelText: "Cancel",
      variant: "destructive",
    });

    if (!confirmed) return;

    try {
      router.push("/c");

      await chatApi.deleteAllConversations();

      // Clear conversations in store immediately
      clearConversations();

      // Then fetch from the API to ensure sync with server
      await fetchConversations(1, 20, false);

      updateConvoMessages([]);
      // Toast is already shown by the API service
    } catch (error) {
      // Error toast is already shown by the API service
      console.error("Error clearing chats:", error);
    }
  };

  const items: MenuItem[] = [
    // Only show Upgrade to Pro if user doesn't have active subscription
    ...(subscriptionStatus?.is_subscribed
      ? []
      : [
          {
            key: "upgrade_to_pro",
            label: (
              <div className="flex items-center gap-2 text-primary">
                <CircleArrowUp width={18} height={18} color="#00bbff" />
                Upgrade to Pro
              </div>
            ),
            action: () => router.push("/pricing"),
          },
        ]),

    // {
    //   key: "contact_support",
    //   label: (
    //     <div className="flex items-center gap-2">
    //       <CustomerService01Icon color={"#9b9b9b"} width={18} />
    //       Contact Support
    //     </div>
    //   ),
    //   action: () => setSupportModalOpen(true),
    // },
    // {
    //   key: "feature_request",
    //   label: (
    //     <div className="flex items-center gap-2">
    //       <BubbleChatQuestionIcon color={"#9b9b9b"} width={18} />
    //       Feature Request
    //     </div>
    //   ),
    //   action: () => setSupportModalOpen(true),
    // },
    {
      key: "manage_memories",
      label: (
        <div className="flex items-center gap-2">
          <Brain02Icon color="#9b9b9b" width={18} />
          Memories
        </div>
      ),
      action: () => router.push("/settings?section=memory"),
    },
    {
      key: "discord",
      label: (
        <div className="flex items-center gap-2 text-[#5865F2]">
          <DiscordIcon color="#5865F2" width={18} />
          {discordLink?.description || "Join our Discord"}
        </div>
      ),
      action: () =>
        window.open(
          discordLink?.href || "https://discord.heygaia.io",
          "_blank",
        ),
    },
    {
      key: "whatsapp",
      label: (
        <div className="flex items-center gap-2 text-[#25d366]">
          <WhatsappIcon color="#25d366" width={18} />
          {whatsappLink?.description || "WhatsApp Community"}
        </div>
      ),
      action: () =>
        window.open(
          whatsappLink?.href || "https://whatsapp.heygaia.io",
          "_blank",
        ),
    },
    {
      key: "settings",
      label: (
        <div className="flex items-center gap-2">
          <Settings01Icon color="#9b9b9b" width={18} />
          Settings
        </div>
      ),
      action: () => router.push("/settings"),
    },
  ];

  return (
    <>
      <Dropdown className="text-foreground dark">
        <DropdownTrigger>{children}</DropdownTrigger>
        <DropdownMenu aria-label="Dynamic Actions">
          {items.map((item) => (
            <DropdownItem
              key={item.key}
              className={item.color === "danger" ? "text-danger" : ""}
              color={item.color === "danger" ? "danger" : "default"}
              textValue={item.key}
              onPress={item.action}
            >
              {item.label}
            </DropdownItem>
          ))}
        </DropdownMenu>
      </Dropdown>

      <ContactSupportModal
        isOpen={supportModalOpen}
        onOpenChange={() => setSupportModalOpen(false)}
      />

      <ConfirmationDialog {...confirmationProps} />
    </>
  );
}
