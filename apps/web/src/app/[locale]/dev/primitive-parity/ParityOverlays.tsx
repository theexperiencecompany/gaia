"use client";

import {
  Dropdown,
  ListBox,
  Modal,
  Popover,
  Select,
  Tooltip,
} from "@heroui/react";
import { Copy01Icon, Delete02Icon, Settings01Icon } from "@icons";
import {
  modalVariants,
  overlayVariants,
} from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";

/** Marks an open overlay for the parity harness, which walks up from it to the overlay's parts. */
function Mark({ id, children }: { id: string; children: string }) {
  return <span data-parity-mark={id}>{children}</span>;
}

const TOOLTIPS = [
  { id: "tooltip/default", showArrow: false, surface: "default" },
  { id: "tooltip/arrow", showArrow: true, surface: "default" },
  { id: "tooltip/primary-arrow", showArrow: true, surface: "accent" },
  { id: "tooltip/foreground-arrow", showArrow: true, surface: "foreground" },
] as const;

const MODAL_SIZES = {
  "modal/sm": "sm",
  "modal/md": "md",
  "modal/lg": "lg",
  "modal/2xl": "2xl",
} as const;

function ParityModal({ id }: { id: keyof typeof MODAL_SIZES }) {
  const size = MODAL_SIZES[id];
  const wide = size === "2xl";
  return (
    <Modal isOpen>
      <Modal.Backdrop>
        <Modal.Container size={wide ? undefined : size}>
          <Modal.Dialog className={wide ? modalVariants({ size }) : undefined}>
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header>
              <Mark id={id}>Modal title</Mark>
            </Modal.Header>
            <Modal.Body>Body text of the modal.</Modal.Body>
            <Modal.Footer>
              <GaiaButton variant="ghost">Cancel</GaiaButton>
              <GaiaButton variant="primary">Confirm</GaiaButton>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}

/** One open overlay (or every tooltip at once), forced open for the parity harness. */
export function ParityOverlays({ overlay }: { overlay: string }) {
  if (overlay === "tooltips") {
    return (
      <div className="grid grid-cols-2 gap-x-40 gap-y-28 p-24">
        {TOOLTIPS.map(({ id, showArrow, surface }) => (
          <Tooltip key={id} isOpen>
            <GaiaButton variant="default-soft" data-parity-trigger={id}>
              {id}
            </GaiaButton>
            <Tooltip.Content
              placement="top"
              showArrow={showArrow}
              className={overlayVariants({ surface })}
            >
              {showArrow ? <Tooltip.Arrow /> : null}
              <Mark id={id}>Tooltip text</Mark>
            </Tooltip.Content>
          </Tooltip>
        ))}
      </div>
    );
  }
  if (overlay === "tooltip-delay") {
    return (
      <div className="p-24">
        <Tooltip>
          <GaiaButton variant="default-soft" data-parity-delay="tooltip/delay">
            Hover me
          </GaiaButton>
          <Tooltip.Content placement="top">
            <Mark id="tooltip/delay">Delayed</Mark>
          </Tooltip.Content>
        </Tooltip>
      </div>
    );
  }
  if (overlay in MODAL_SIZES) {
    return <ParityModal id={overlay as keyof typeof MODAL_SIZES} />;
  }
  return (
    <div className="flex justify-center p-32">
      {overlay === "popover/default" || overlay === "popover/arrow" ? (
        <Popover isOpen>
          <GaiaButton variant="default-soft" data-parity-trigger={overlay}>
            Trigger
          </GaiaButton>
          <Popover.Content placement="bottom">
            {overlay === "popover/arrow" ? <Popover.Arrow /> : null}
            <Popover.Dialog>
              <Mark id={overlay}>Popover body text</Mark>
            </Popover.Dialog>
          </Popover.Content>
        </Popover>
      ) : null}
      {overlay === "dropdown/menu" ? (
        <Dropdown isOpen>
          <GaiaButton
            variant="default-soft"
            data-parity-trigger="dropdown/menu"
          >
            Trigger
          </GaiaButton>
          <Dropdown.Popover placement="bottom">
            <Dropdown.Menu aria-label="Menu">
              <Dropdown.Item id="plain" textValue="Plain">
                <Mark id="dropdown/menu">Plain item</Mark>
              </Dropdown.Item>
              <Dropdown.Item id="icon" textValue="With icon">
                <Settings01Icon size={16} />
                With icon
              </Dropdown.Item>
              <Dropdown.Item id="copy" textValue="Copy">
                <Copy01Icon size={16} />
                Copy
              </Dropdown.Item>
              <Dropdown.Item id="delete" textValue="Delete" variant="danger">
                <Delete02Icon size={16} />
                Delete
              </Dropdown.Item>
            </Dropdown.Menu>
          </Dropdown.Popover>
        </Dropdown>
      ) : null}
      {overlay === "select/open" ? (
        <div data-parity-open>
          <Select
            aria-label="Profession"
            defaultSelectedKey="Designer"
            className="w-72"
          >
            <Select.Trigger>
              <GaiaSelectValue />
              <Select.Indicator />
            </Select.Trigger>
            <Select.Popover>
              <ListBox>
                {["Engineer", "Designer", "Founder"].map((option) => (
                  <GaiaListBoxItem key={option} id={option} textValue={option}>
                    <Mark id={`select/open/${option}`}>{option}</Mark>
                  </GaiaListBoxItem>
                ))}
              </ListBox>
            </Select.Popover>
          </Select>
        </div>
      ) : null}
    </div>
  );
}
