"use client";

import { Dropdown, Header, Separator } from "@heroui/react";
import {
  BookBookmark02Icon,
  BubbleChatQuestionIcon,
  GitPullRequestIcon,
  Layers01Icon,
  MapsIcon,
  QuillWrite01Icon,
} from "@icons";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { Fragment, type ReactNode, useState } from "react";
import { useKeyboardShortcuts } from "@/components/providers/KeyboardShortcutsProvider";
import {
  type ConfirmAction,
  ConfirmActionDialog,
} from "@/components/shared/ConfirmActionDialog";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { overlayVariants } from "@/components/shared/controlVariants";
import { ChevronRight, Github } from "@/components/shared/icons";
import { toneVariants } from "@/components/shared/tone";
import { getLinkByLabel } from "@/config/appConfig";
import ContactSupportModal from "@/features/support/components/ContactSupportModal";
import { WhatsNewTimelineMenu } from "@/features/whats-new/components/WhatsNewTimelineMenu";
import {
  type PlatformInfo,
  usePlatformDetection,
} from "@/hooks/ui/usePlatformDetection";
import { useConfirmation } from "@/hooks/useConfirmation";
import { useNestedMenu } from "../hooks/useNestedMenu";
import {
  type SettingsMenuItem,
  useSettingsMenuSections,
} from "../hooks/useSettingsMenuSections";
import { NestedMenuTooltip } from "./NestedMenuTooltip";

export type ModalAction = "clear_chats" | "logout";

const ICON_CLASSES = "w-[18px] h-[18px]";

const socialMediaColorMap: Record<string, string> = {
  discord: "#5865F2",
  whatsapp: "#25d366",
};

interface SubmenuControllers {
  whatsNewMenu: ReturnType<typeof useNestedMenu>;
  downloadMenu: ReturnType<typeof useNestedMenu>;
  resourcesMenu: ReturnType<typeof useNestedMenu>;
  supportMenu: ReturnType<typeof useNestedMenu>;
}

/** The four submenu flyouts anchored to their settings-menu items. */
function SettingsSubmenuFlyouts({
  menus,
  currentPlatform,
  desktopPlatforms,
  onOpenSupportModal,
  onWhatsNewClosed,
}: {
  menus: SubmenuControllers;
  currentPlatform: PlatformInfo;
  desktopPlatforms: PlatformInfo[];
  onOpenSupportModal: (type: string) => void;
  /** Runs after the What's-new flyout closes so the parent can close itself too. */
  onWhatsNewClosed: () => void;
}) {
  const router = useRouter();
  const docsLink = getLinkByLabel("Documentation");
  const githubLink = getLinkByLabel("GitHub");

  const resourcesMenuItems = [
    {
      key: "documentation",
      label: "Documentation",
      icon: BookBookmark02Icon,
      action: () =>
        window.open(docsLink?.href, "_blank", "noopener,noreferrer"),
    },
    {
      key: "release-notes",
      label: "Release Notes",
      icon: Layers01Icon,
      action: () =>
        window.open(
          "https://docs.heygaia.io/release-notes",
          "_blank",
          "noopener,noreferrer",
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
        window.open(
          "https://gaia.featurebase.app/roadmap",
          "_blank",
          "noopener,noreferrer",
        ),
    },
    {
      key: "opensource",
      label: "Open Source",
      icon: Github,
      action: () =>
        window.open(githubLink?.href, "_blank", "noopener,noreferrer"),
    },
  ];

  const supportMenuItems = [
    {
      key: "contact_support",
      label: "Contact Support",
      icon: BubbleChatQuestionIcon,
      action: () => onOpenSupportModal("support"),
    },
    {
      key: "feature_request",
      label: "Request a Feature",
      icon: GitPullRequestIcon,
      action: () => onOpenSupportModal("feature"),
    },
  ];

  // Sort platforms with current platform first
  const sortedPlatforms = [
    ...desktopPlatforms.filter((p) => p.platform === currentPlatform.platform),
    ...desktopPlatforms.filter((p) => p.platform !== currentPlatform.platform),
  ];

  const downloadMenuItems = sortedPlatforms.map((platform: PlatformInfo) => ({
    key: platform.platform,
    label: platform.shortName,
    iconElement: (
      <div className="relative h-[18px] w-[18px]">
        <Image
          src={platform.iconPath}
          alt={platform.displayName}
          fill
          sizes="18px"
          className="object-contain"
        />
      </div>
    ),
    action: () => {
      if (platform.downloadUrl) {
        window.open(platform.downloadUrl, "_blank", "noopener,noreferrer");
      } else {
        router.push("/download");
      }
    },
  }));

  return (
    <>
      <NestedMenuTooltip
        isOpen={menus.whatsNewMenu.isOpen}
        onOpenChange={menus.whatsNewMenu.setIsOpen}
        itemRef={menus.whatsNewMenu.itemRef}
        customContent={
          <WhatsNewTimelineMenu
            onClose={() => {
              menus.whatsNewMenu.setIsOpen(false);
              onWhatsNewClosed();
            }}
          />
        }
      />

      <NestedMenuTooltip
        isOpen={menus.resourcesMenu.isOpen}
        onOpenChange={menus.resourcesMenu.setIsOpen}
        itemRef={menus.resourcesMenu.itemRef}
        menuItems={resourcesMenuItems}
        iconClasses={ICON_CLASSES}
      />

      <NestedMenuTooltip
        isOpen={menus.supportMenu.isOpen}
        onOpenChange={menus.supportMenu.setIsOpen}
        itemRef={menus.supportMenu.itemRef}
        menuItems={supportMenuItems}
        iconClasses={ICON_CLASSES}
      />

      <NestedMenuTooltip
        isOpen={menus.downloadMenu.isOpen}
        onOpenChange={menus.downloadMenu.setIsOpen}
        itemRef={menus.downloadMenu.itemRef}
        menuItems={downloadMenuItems}
        iconClasses={ICON_CLASSES}
      />
    </>
  );
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
  const docsLink = getLinkByLabel("Documentation");
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [supportModalOpen, setSupportModalOpen] = useState(false);
  const [supportModalType, setSupportModalType] = useState<
    string | undefined
  >();
  const [modalAction, setModalAction] = useState<ModalAction | null>(null);

  const whatsNewMenu = useNestedMenu();
  const resourcesMenu = useNestedMenu();
  const supportMenu = useNestedMenu();
  const downloadMenu = useNestedMenu();

  // Maps a submenu item's key to the nested-menu controller driving its flyout.
  const submenuByKey: Record<string, ReturnType<typeof useNestedMenu>> = {
    "whats-new": whatsNewMenu,
    download: downloadMenu,
    resources: resourcesMenu,
    support: supportMenu,
  };

  const { currentPlatform, desktopPlatforms } = usePlatformDetection();
  const { openShortcutsModal } = useKeyboardShortcuts();

  const openSupportModal = (type: string) => {
    setSupportModalType(type);
    setSupportModalOpen(true);
  };

  const handleItemAction = (item: SettingsMenuItem) => {
    if (item.href) {
      router.push(item.href);
    } else if (item.action) {
      item.action();
    } else if (item.external) {
      const linkMap: Record<string, string | undefined> = {
        discord: discordLink?.href,
        whatsapp: whatsappLink?.href,
        documentation: docsLink?.href,
      };
      const url = linkMap[item.key];
      if (url) window.open(url, "_blank", "noopener,noreferrer");
    }
  };

  const menuSections = useSettingsMenuSections({
    onOpenShortcuts: openShortcutsModal,
    onSignOut: () => setModalAction("logout"),
    downloadLabel: `Download for ${currentPlatform.isMobile ? "Desktop" : currentPlatform.shortName.split(" ")[0]}`,
  });

  return (
    <>
      <Dropdown
        isOpen={isMenuOpen}
        onOpenChange={(open) => {
          setIsMenuOpen(open);
          // The flyouts are anchored to menu items that unmount with the
          // menu; left open, one keeps floating after the menu is gone.
          if (!open) {
            for (const menu of Object.values(submenuByKey)) {
              menu.setIsOpen(false);
            }
          }
          onOpenChange?.(open);
        }}
      >
        {children}
        <Dropdown.Popover
          placement="right"
          offset={21}
          className={overlayVariants({
            surface: "secondary",
            className: "dark shadow-xl",
          })}
        >
          <Dropdown.Menu aria-label="Settings Menu">
            {menuSections.map((section) => (
              <Fragment key={section.id}>
                <Dropdown.Section>
                  {section.title && <Header>{section.title}</Header>}
                  {section.items.map((item: SettingsMenuItem) => {
                    const Icon = item.icon;
                    const iconColor =
                      item.iconColor || socialMediaColorMap[item.key];
                    const isQuiet = item.color !== "danger" && !iconColor;
                    const itemClassName = toneVariants({
                      tone: isQuiet ? "muted" : "default",
                      interactive: isQuiet,
                      className: item.customClassNames?.title,
                    });

                    // Handle nested menus (What's new, Download, Resources, Support)
                    if (item.hasSubmenu) {
                      const menu = submenuByKey[item.key] ?? supportMenu;

                      return (
                        <Dropdown.Item
                          key={item.key}
                          id={item.key}
                          textValue={item.label}
                          onMouseEnter={menu.handleMouseEnter}
                          onMouseLeave={menu.handleMouseLeave}
                          className={toneVariants({
                            tone: "muted",
                            interactive: true,
                          })}
                        >
                          {Icon && <Icon className={ICON_CLASSES} />}
                          {item.label}
                          <div className="ml-auto flex items-center gap-1.5">
                            {item.badge}
                            <ChevronRight className="h-4 w-4 text-zinc-500" />
                          </div>
                        </Dropdown.Item>
                      );
                    }

                    return (
                      <Dropdown.Item
                        key={item.key}
                        id={item.key}
                        textValue={item.label}
                        variant={item.color === "danger" ? "danger" : "default"}
                        onAction={() => handleItemAction(item)}
                        className={itemClassName}
                        style={iconColor ? { color: iconColor } : undefined}
                      >
                        {item.iconElement ??
                          (Icon && (
                            <Icon className={ICON_CLASSES} color={iconColor} />
                          ))}
                        {item.label}
                      </Dropdown.Item>
                    );
                  })}
                </Dropdown.Section>
                {section.showDivider && <Separator />}
              </Fragment>
            ))}
          </Dropdown.Menu>
        </Dropdown.Popover>
      </Dropdown>

      <SettingsSubmenuFlyouts
        menus={{ whatsNewMenu, downloadMenu, resourcesMenu, supportMenu }}
        currentPlatform={currentPlatform}
        desktopPlatforms={desktopPlatforms}
        onOpenSupportModal={openSupportModal}
        onWhatsNewClosed={() => {
          setIsMenuOpen(false);
          onOpenChange?.(false);
        }}
      />

      <ContactSupportModal
        isOpen={supportModalOpen}
        onOpenChange={() => {
          setSupportModalOpen(false);
          setSupportModalType(undefined);
        }}
        initialValues={
          supportModalType ? { type: supportModalType } : undefined
        }
      />

      <ConfirmActionDialog
        action={modalAction as ConfirmAction}
        onOpenChange={(action) => setModalAction(action as ModalAction)}
      />

      <ConfirmationDialog {...confirmationProps} />
    </>
  );
}
