"use client";

import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownSection,
  DropdownTrigger,
} from "@heroui/dropdown";
import { BookIcon, ChevronRight, CircleArrowUp, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { ReactNode, useState } from "react";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import {
  BookOpen01Icon,
  BubbleChatQuestionIcon,
  CustomerService01Icon,
  Github,
  QuillWrite01Icon,
  Settings01Icon,
  ThreeDotsMenu,
} from "@/components/shared/icons";
import { getLinkByLabel } from "@/config/appConfig";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import { ContactSupportModal } from "@/features/support";
import { useConfirmation } from "@/hooks/useConfirmation";

import { settingsPageItems, socialMediaItems } from "../config/settingsConfig";
import { useNestedMenu } from "../hooks/useNestedMenu";
import LogoutModal from "./LogoutModal";
import { NestedMenuTooltip } from "./NestedMenuTooltip";

export type ModalAction = "clear_chats" | "logout";

interface MenuItem {
  key: string;
  label: string;
  icon?: React.ElementType;
  href?: string;
  action?: () => void;
  color?: "danger" | "default";
  external?: boolean;
  hasSubmenu?: boolean;
  iconColor?: string;
  customClassNames?: {
    title?: string;
  };
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
  const githubLink = getLinkByLabel("GitHub");
  const [supportModalOpen, setSupportModalOpen] = useState(false);
  const [modalAction, setModalAction] = useState<ModalAction | null>(null);
  const { data: subscriptionStatus } = useUserSubscriptionStatus();

  const resourcesMenu = useNestedMenu();
  const supportMenu = useNestedMenu();

  const iconClasses = "w-[18px] h-[18px]";

  const resourcesMenuItems = [
    {
      key: "documentation",
      label: "Documentation",
      icon: BookOpen01Icon,
      action: () => window.open(docsLink?.href, "_blank"),
    },
    {
      key: "changelog",
      label: "Changelog",
      icon: BookIcon,
      action: () => router.push("/changelog"),
    },
    {
      key: "blog",
      label: "Blog",
      icon: QuillWrite01Icon,
      action: () => router.push("/blog"),
    },
    {
      key: "roadmap",
      label: "Roadmap",
      icon: BookOpen01Icon,
      action: () => window.open("https://roadmap.heygaia.ai", "_blank"),
    },
    {
      key: "opensource",
      label: "Open Source",
      icon: Github,
      action: () => window.open(githubLink?.href, "_blank"),
    },
  ];

  const supportMenuItems = [
    {
      key: "contact_support",
      label: "Contact Support",
      icon: CustomerService01Icon,
      action: () => setSupportModalOpen(true),
    },
    {
      key: "feature_request",
      label: "Request a Feature",
      icon: BubbleChatQuestionIcon,
      action: () => setSupportModalOpen(true),
    },
  ];

  const socialMediaColorMap: Record<string, string> = {
    twitter: "#1da1f2",
    discord: "#5865F2",
    whatsapp: "#25d366",
  };

  const handleItemAction = (item: MenuItem) => {
    if (item.href) {
      router.push(item.href);
    } else if (item.action) {
      item.action();
    } else if (item.external) {
      const linkMap: Record<string, string | undefined> = {
        discord: discordLink?.href,
        whatsapp: whatsappLink?.href,
        twitter: twitterLink?.href,
        documentation: docsLink?.href,
      };
      const url = linkMap[item.key];
      if (url) window.open(url, "_blank");
    }
  };

  const menuSections = [
    ...(subscriptionStatus?.is_subscribed
      ? []
      : [
          {
            title: undefined,
            showDivider: true,
            items: [
              {
                key: "upgrade_to_pro",
                label: "Upgrade to Pro",
                action: () => router.push("/pricing"),
                icon: CircleArrowUp,
                iconColor: "#00bbff",
                customClassNames: { title: "text-primary font-medium" },
              },
            ],
          },
        ]),
    {
      title: "Settings",
      showDivider: true,
      items: [
        ...settingsPageItems.filter((item) => item.key !== "subscription"),
      ],
    },
    {
      title: "Community",
      showDivider: true,
      items: socialMediaItems,
    },
    {
      title: undefined,
      showDivider: false,
      items: [
        {
          key: "resources",
          label: "Resources",
          icon: BookOpen01Icon,
          hasSubmenu: true,
        },
        {
          key: "support",
          label: "Support",
          icon: CustomerService01Icon,
          hasSubmenu: true,
        },
        {
          key: "settings",
          label: "Settings",
          icon: Settings01Icon,
          action: () => router.push("/settings"),
        },
        {
          key: "logout",
          label: "Sign Out",
          icon: LogOut,
          color: "danger" as const,
          action: () => setModalAction("logout"),
        },
      ],
    },
  ];

  return (
    <>
      <Dropdown
        placement="right"
        className="bg-[#141414] text-foreground dark shadow-xl"
        offset={21}
      >
        <DropdownTrigger>{children}</DropdownTrigger>
        <DropdownMenu aria-label="Settings Menu" variant="faded">
          {menuSections.map((section, index) => (
            <DropdownSection
              key={section.title || `section-${index}`}
              title={section.title}
              showDivider={section.showDivider}
              classNames={{ divider: "bg-zinc-800/60" }}
            >
              {section.items.map((item: MenuItem) => {
                const Icon = item.icon;
                const iconColor =
                  item.iconColor || socialMediaColorMap[item.key];

                // Handle nested menus (Resources and Support)
                if (item.hasSubmenu) {
                  const menu =
                    item.key === "resources" ? resourcesMenu : supportMenu;

                  return (
                    <DropdownItem
                      key={item.key}
                      textValue={item.label}
                      variant="flat"
                      onMouseEnter={menu.handleMouseEnter}
                      onMouseLeave={menu.handleMouseLeave}
                      className="text-zinc-400 transition hover:text-white"
                      startContent={Icon && <Icon className={iconClasses} />}
                      endContent={
                        <ChevronRight className="h-4 w-4 text-zinc-500" />
                      }
                    >
                      {item.label}
                    </DropdownItem>
                  );
                }

                return (
                  <DropdownItem
                    key={item.key}
                    textValue={item.label}
                    variant="flat"
                    color={item.color}
                    onPress={() => handleItemAction(item)}
                    className={
                      item.color === "danger"
                        ? "text-danger"
                        : iconColor
                          ? "transition"
                          : "text-zinc-400 transition hover:text-white"
                    }
                    style={iconColor ? { color: iconColor } : undefined}
                    startContent={
                      Icon && <Icon className={iconClasses} color={iconColor} />
                    }
                    classNames={item.customClassNames}
                  >
                    {item.label}
                  </DropdownItem>
                );
              })}
            </DropdownSection>
          ))}
        </DropdownMenu>
      </Dropdown>

      <NestedMenuTooltip
        isOpen={resourcesMenu.isOpen}
        onOpenChange={resourcesMenu.setIsOpen}
        itemRef={resourcesMenu.itemRef}
        menuItems={resourcesMenuItems}
        iconClasses={iconClasses}
      />

      <NestedMenuTooltip
        isOpen={supportMenu.isOpen}
        onOpenChange={supportMenu.setIsOpen}
        itemRef={supportMenu.itemRef}
        menuItems={supportMenuItems}
        iconClasses={iconClasses}
      />

      <ContactSupportModal
        isOpen={supportModalOpen}
        onOpenChange={() => setSupportModalOpen(false)}
      />

      <LogoutModal modalAction={modalAction} setModalAction={setModalAction} />

      <ConfirmationDialog {...confirmationProps} />
    </>
  );
}
