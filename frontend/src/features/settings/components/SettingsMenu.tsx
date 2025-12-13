"use client";

import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownSection,
  DropdownTrigger,
} from "@heroui/dropdown";
import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";
import {
  type ConfirmAction,
  ConfirmActionDialog,
} from "@/components/shared/ConfirmActionDialog";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { getLinkByLabel } from "@/config/appConfig";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import { ContactSupportModal } from "@/features/support";
import { useConfirmation } from "@/hooks/useConfirmation";
import {
  ArrowRight01Icon,
  BookBookmark02Icon,
  BookOpen02Icon,
  BubbleChatQuestionIcon,
  CircleArrowUp02Icon,
  CustomerService01Icon,
  Github,
  GitPullRequestIcon,
  Layers01Icon,
  Logout02Icon,
  MapsIcon,
  QuillWrite01Icon,
  Settings01Icon,
} from "@/icons";

import { settingsPageItems, socialMediaItems } from "../config/settingsConfig";
import { useNestedMenu } from "../hooks/useNestedMenu";
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
  children,
  onOpenChange,
}: {
  children?: ReactNode;
  onOpenChange?: (isOpen: boolean) => void;
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
      icon: BookBookmark02Icon,
      action: () => window.open(docsLink?.href, "_blank"),
    },
    {
      key: "changelog",
      label: "Changelog",
      icon: Layers01Icon,
      action: () =>
        window.open(
          "https://github.com/theexperiencecompany/gaia/releases",
          "_blank",
        ),
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
      icon: MapsIcon,
      action: () =>
        window.open("https://gaia.featurebase.app/roadmap", "_blank"),
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
      icon: BubbleChatQuestionIcon,
      action: () => setSupportModalOpen(true),
    },
    {
      key: "feature_request",
      label: "Request a Feature",
      icon: GitPullRequestIcon,
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
                icon: CircleArrowUp02Icon,
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
          icon: BookOpen02Icon,
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
          icon: Logout02Icon,
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
        className="bg-secondary-bg text-foreground dark shadow-xl"
        offset={21}
        onOpenChange={onOpenChange}
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
                        <ArrowRight01Icon className="h-4 w-4 text-zinc-500" />
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

      <ConfirmActionDialog
        action={modalAction as ConfirmAction}
        onOpenChange={(action) => setModalAction(action as ModalAction)}
      />

      <ConfirmationDialog {...confirmationProps} />
    </>
  );
}
