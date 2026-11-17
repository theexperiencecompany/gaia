"use client";

import { ButtonGroup, Dropdown, Tooltip } from "@heroui/react";
import {
  ArrowDown01Icon,
  Copy01Icon,
  Download01Icon,
  Mic01Icon,
  PaintBoardIcon,
  ReloadIcon,
  Share08Icon,
} from "@icons";
import {
  GaiaButton,
  type GaiaButtonVariant,
} from "@/components/shared/GaiaButton";
import type { Shape } from "@/components/shared/shape";
import { shapeVariants } from "@/components/shared/shape";

import { ParityCell, ParitySection } from "./ParityCell";

interface ButtonCombo {
  id: string;
  variant: GaiaButtonVariant;
  size?: "sm" | "md" | "lg";
  shape?: Shape;
  isIconOnly?: boolean;
  fullWidth?: boolean;
  isDisabled?: boolean;
}

/** v2's Button combinations by use count, each on the variant the migration maps it to (decisions.json). */
const BUTTONS: ButtonCombo[] = [
  { id: "button/primary-md", variant: "primary" },
  { id: "button/primary-sm", variant: "primary", size: "sm" },
  { id: "button/primary-lg", variant: "primary", size: "lg" },
  { id: "button/primary-pill", variant: "primary", shape: "pill" },
  { id: "button/default-md", variant: "default-solid" },
  { id: "button/default-sm", variant: "default-solid", size: "sm" },
  { id: "button/flat-md", variant: "default-soft" },
  { id: "button/flat-sm", variant: "default-soft", size: "sm" },
  { id: "button/flat-primary-md", variant: "accent-soft" },
  { id: "button/flat-primary-sm", variant: "accent-soft", size: "sm" },
  { id: "button/flat-danger-sm", variant: "danger-soft", size: "sm" },
  { id: "button/flat-success-sm", variant: "success-soft", size: "sm" },
  { id: "button/flat-warning-sm", variant: "warning-soft", size: "sm" },
  { id: "button/light-md", variant: "ghost" },
  { id: "button/light-sm", variant: "ghost", size: "sm" },
  { id: "button/light-icon-md", variant: "ghost", isIconOnly: true },
  {
    id: "button/light-icon-sm",
    variant: "ghost",
    size: "sm",
    isIconOnly: true,
  },
  {
    id: "button/light-icon-sm-pill",
    variant: "ghost",
    size: "sm",
    isIconOnly: true,
    shape: "pill",
  },
  { id: "button/flat-icon-md", variant: "default-soft", isIconOnly: true },
  {
    id: "button/flat-icon-md-pill",
    variant: "default-soft",
    isIconOnly: true,
    shape: "pill",
  },
  {
    id: "button/flat-icon-sm",
    variant: "default-soft",
    size: "sm",
    isIconOnly: true,
  },
  {
    id: "button/flat-icon-sm-pill",
    variant: "default-soft",
    size: "sm",
    isIconOnly: true,
    shape: "pill",
  },
  {
    id: "button/default-icon-sm",
    variant: "default-solid",
    size: "sm",
    isIconOnly: true,
  },
  {
    id: "button/flat-primary-sm-full",
    variant: "accent-soft",
    size: "sm",
    fullWidth: true,
  },
  { id: "button/light-sm-full", variant: "ghost", size: "sm", fullWidth: true },
  {
    id: "button/flat-primary-sm-disabled",
    variant: "accent-soft",
    size: "sm",
    isDisabled: true,
  },
  { id: "button/primary-md-disabled", variant: "primary", isDisabled: true },
];

type IconEntry = readonly [string, typeof Copy01Icon];

const TOOLBAR: IconEntry[] = [
  ["share", Share08Icon],
  ["palette", PaintBoardIcon],
  ["duplicate", ReloadIcon],
  ["download", Download01Icon],
];
const PAIR: IconEntry[] = [
  ["copy", Copy01Icon],
  ["share", Share08Icon],
];
const VOICE_BAR: IconEntry[] = [
  ["mic", Mic01Icon],
  ["copy", Copy01Icon],
  ["share", Share08Icon],
];

/** Every Button and ButtonGroup combination v2 rendered, for the parity harness. */
export function ParityButtons() {
  return (
    <>
      <ParitySection title="Button">
        {BUTTONS.map(({ id, isIconOnly, fullWidth, ...props }) => (
          <ParityCell key={id} id={id} wide={fullWidth}>
            <GaiaButton
              isIconOnly={isIconOnly}
              fullWidth={fullWidth}
              aria-label={id}
              {...props}
            >
              {isIconOnly ? <Copy01Icon size={18} /> : "Button"}
            </GaiaButton>
          </ParityCell>
        ))}
      </ParitySection>
      <ParitySection title="ButtonGroup">
        <ParityCell id="buttongroup/split-primary">
          <ButtonGroup>
            <GaiaButton variant="primary">Download</GaiaButton>
            <Dropdown>
              <GaiaButton aria-label="More" isIconOnly variant="primary">
                <ArrowDown01Icon size={17} />
              </GaiaButton>
              <Dropdown.Popover>
                <Dropdown.Menu aria-label="More">
                  <Dropdown.Item id="a" textValue="A">
                    A
                  </Dropdown.Item>
                </Dropdown.Menu>
              </Dropdown.Popover>
            </Dropdown>
          </ButtonGroup>
        </ParityCell>
        <ParityCell id="buttongroup/tooltip-icons">
          <ButtonGroup>
            {TOOLBAR.map(([name, Icon], index) => (
              <Tooltip key={name}>
                <Tooltip.Trigger>
                  <GaiaButton
                    isIconOnly
                    variant="default-soft"
                    aria-label={`Action ${index}`}
                  >
                    <Icon size={20} />
                  </GaiaButton>
                </Tooltip.Trigger>
                <Tooltip.Content placement="top">Action</Tooltip.Content>
              </Tooltip>
            ))}
          </ButtonGroup>
        </ParityCell>
        <ParityCell id="buttongroup/tooltip-direct-sm">
          <ButtonGroup>
            {PAIR.map(([name, Icon], index) => (
              <Tooltip key={name}>
                <GaiaButton
                  isIconOnly
                  size="sm"
                  variant="default-soft"
                  aria-label={`Action ${index}`}
                >
                  <Icon size={16} />
                </GaiaButton>
                <Tooltip.Content>Action</Tooltip.Content>
              </Tooltip>
            ))}
          </ButtonGroup>
        </ParityCell>
        <ParityCell id="buttongroup/flat-full" wide>
          <ButtonGroup fullWidth>
            <GaiaButton variant="default-soft" fullWidth>
              Settings
            </GaiaButton>
            <GaiaButton variant="danger-soft" fullWidth>
              Disconnect
            </GaiaButton>
          </ButtonGroup>
        </ParityCell>
        <ParityCell id="buttongroup/flat-pill-icons">
          <ButtonGroup className={shapeVariants({ shape: "pill" })}>
            {VOICE_BAR.map(([name, Icon], index) => (
              <GaiaButton
                key={name}
                isIconOnly
                variant="default-soft"
                aria-label={`Action ${index}`}
              >
                <Icon size={18} />
              </GaiaButton>
            ))}
          </ButtonGroup>
        </ParityCell>
        <ParityCell id="buttongroup/warning-sm">
          <ButtonGroup size="sm">
            <GaiaButton variant="warning-soft" size="sm">
              Connect Apps
            </GaiaButton>
            <GaiaButton
              variant="warning-soft"
              size="sm"
              isIconOnly
              aria-label="More"
            >
              <ArrowDown01Icon size={16} />
            </GaiaButton>
          </ButtonGroup>
        </ParityCell>
      </ParitySection>
    </>
  );
}
