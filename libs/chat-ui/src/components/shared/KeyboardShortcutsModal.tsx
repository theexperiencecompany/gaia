"use client";

import { Modal, ModalBody, ModalContent, ModalHeader } from "@heroui/modal";

import {
  getShortcutsByCategory,
  type KeyboardShortcut,
  ShortcutKeysDisplay,
} from "@/config/keyboardShortcuts";

interface KeyboardShortcutsModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

function ShortcutCategory({
  title,
  shortcuts,
}: {
  title: string;
  shortcuts: KeyboardShortcut[];
}) {
  if (shortcuts.length === 0) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-zinc-400">{title}</h3>
      <div className="space-y-1">
        {shortcuts.map((shortcut) => (
          <div
            key={shortcut.id}
            className="flex items-center justify-between py-2"
          >
            <div className="flex items-center gap-3">
              {shortcut.icon && (
                <span className="text-zinc-400">{shortcut.icon}</span>
              )}
              <span className="text-sm font-light text-zinc-300">
                {shortcut.description}
              </span>
            </div>
            <ShortcutKeysDisplay keys={shortcut.keys} size="md" />
          </div>
        ))}
      </div>
    </div>
  );
}

export default function KeyboardShortcutsModal({
  isOpen,
  onOpenChange,
}: KeyboardShortcutsModalProps) {
  const createShortcuts = getShortcutsByCategory("create");
  const navigationShortcuts = getShortcutsByCategory("navigation");
  const generalShortcuts = getShortcutsByCategory("general");

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      size="4xl"
      backdrop="blur"
      className="rounded-2xl bg-zinc-900/90 backdrop-blur-3xl outline-0 border-0"
    >
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <span className="text-xl font-semibold">Keyboard Shortcuts</span>
        </ModalHeader>

        <ModalBody className="gap-6 pb-6">
          <ShortcutCategory title="Create" shortcuts={createShortcuts} />
          <ShortcutCategory
            title="Navigation"
            shortcuts={navigationShortcuts}
          />
          <ShortcutCategory title="General" shortcuts={generalShortcuts} />
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
