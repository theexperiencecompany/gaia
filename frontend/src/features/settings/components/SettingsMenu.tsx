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

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import {
  BookOpen01Icon,
  Brain02Icon,
  CustomerService01Icon,
  DiscordIcon,
  Settings01Icon,
  ThreeDotsMenu,
  TwitterIcon,
  WhatsappIcon,
} from "@/components/shared/icons";
import { getLinkByLabel } from "@/config/appConfig";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import { ContactSupportModal } from "@/features/support";
import { useConfirmation } from "@/hooks/useConfirmation";

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
  const { confirmationProps } = useConfirmation();

  const discordLink = getLinkByLabel("Discord");
  const whatsappLink = getLinkByLabel("WhatsApp");
  const twitterLink = getLinkByLabel("Twitter");
  const docsLink = getLinkByLabel("Documentation");
  const [supportModalOpen, setSupportModalOpen] = useState(false);
  const { data: subscriptionStatus } = useUserSubscriptionStatus();

  const items: MenuItem[] = [
    {
      key: "manage_memories",
      label: (
        <div className="flex items-center gap-2">
          <BookOpen01Icon color="#9b9b9b" width={18} />
          Documentation
        </div>
      ),
      action: () => window.open(docsLink?.href, "_blank"),
    },

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

    {
      key: "contact_support",
      label: (
        <div className="flex items-center gap-2">
          <CustomerService01Icon color={"#9b9b9b"} width={18} />
          Contact Support
        </div>
      ),
      action: () => setSupportModalOpen(true),
    },
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
      key: "twitter",
      label: (
        <div className="flex items-center gap-2 text-[#1da1f2]">
          <TwitterIcon />
          Follow Us
        </div>
      ),
      action: () => window.open(twitterLink?.href, "_blank"),
    },
    {
      key: "discord",
      label: (
        <div className="flex items-center gap-2 text-[#5865F2]">
          <DiscordIcon color="#5865F2" width={18} />
          Join Discord
        </div>
      ),
      action: () => window.open(discordLink?.href, "_blank"),
    },
    {
      key: "whatsapp",
      label: (
        <div className="flex items-center gap-2 text-[#25d366]">
          <WhatsappIcon color="#25d366" width={18} />
          Join WhatsApp
        </div>
      ),
      action: () => window.open(whatsappLink?.href, "_blank"),
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
      <Dropdown className="text-foreground dark shadow-xl">
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
