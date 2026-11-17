"use client";

import {
  Description,
  InputGroup,
  Label,
  ListBox,
  Modal,
  Radio,
  RadioGroup,
  Select,
  Spinner,
} from "@heroui/react";
import { Alert01Icon, Copy01Icon, RefreshIcon } from "@icons";
import { useState } from "react";
import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { GranteeEmailsInput } from "@/features/short-links/components/GranteeEmailsInput";
import {
  EXPIRY_PRESETS,
  type ExpiryChoice,
  LINK_ACCESS_OPTIONS,
  LINK_ACCESS_ORDER,
} from "@/features/short-links/constants";
import type { ShareLink } from "@/features/short-links/hooks/useShareLink";
import { copyShortLink } from "@/features/short-links/utils/copyShortLink";
import type {
  LinkAccess,
  LinkSettings,
  ShortLinkResponse,
} from "@/types/features/shortLinkTypes";

function isLinkAccess(value: unknown): value is LinkAccess {
  return typeof value === "string" && value in LINK_ACCESS_OPTIONS;
}

function isExpiryChoice(value: string): value is ExpiryChoice {
  return (
    value === "keep" ||
    value === "never" ||
    EXPIRY_PRESETS.some((p) => p.key === value)
  );
}

function expiryChange(choice: ExpiryChoice): Pick<LinkSettings, "expires_at"> {
  if (choice === "keep") return {};
  if (choice === "never") return { expires_at: null };
  const preset = EXPIRY_PRESETS.find((p) => p.key === choice);
  return preset
    ? { expires_at: new Date(Date.now() + preset.ms).toISOString() }
    : {};
}

function describeExpiry(expiresAt: string | null): string {
  if (!expiresAt) return "Never expires";
  const at = new Date(expiresAt).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  return `Expires ${at}`;
}

/** Who an artifact's heygaia.link opens for and until when, plus its URL and a way to replace it. */
export function ShareLinkSettingsModal({ share }: { share: ShareLink }) {
  return (
    <Modal
      isOpen={share.isSettingsOpen}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) share.closeSettings();
      }}
    >
      <Modal.Backdrop isDismissable={!share.isSaving}>
        <Modal.Container scroll="inside">
          <Modal.Dialog>
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header>
              <div className="flex flex-col gap-1">
                <Modal.Heading>Share settings</Modal.Heading>
                <span className="text-sm font-normal text-zinc-400">
                  Who can open this link, and for how long.
                </span>
              </div>
            </Modal.Header>
            {share.link === undefined ? (
              <Modal.Body>
                <div className="flex justify-center py-8">
                  <Spinner size="sm" />
                </div>
              </Modal.Body>
            ) : (
              <ShareSettingsForm share={share} link={share.link} />
            )}
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}

function ShareSettingsForm({
  share,
  link,
}: {
  share: ShareLink;
  link: ShortLinkResponse | null;
}) {
  const [access, setAccess] = useState<LinkAccess>(link?.access ?? "unlisted");
  const [grantees, setGrantees] = useState<string[]>(link?.grantees ?? []);
  const [expiry, setExpiry] = useState<ExpiryChoice>(
    link?.expires_at ? "keep" : "never",
  );
  const [missingPeople, setMissingPeople] = useState(false);
  const [confirmingRotate, setConfirmingRotate] = useState(false);

  const maxAccess = link?.content_max_access;
  const exceedsContent =
    maxAccess != null &&
    LINK_ACCESS_OPTIONS[access].breadth >
      LINK_ACCESS_OPTIONS[maxAccess].breadth;
  const expiryChoices = [
    ...(link?.expires_at ? [{ key: "keep", label: "Keep current" }] : []),
    ...EXPIRY_PRESETS,
    { key: "never", label: "Never" },
  ];

  const save = () => {
    const isPeople = access === "people";
    if (isPeople && grantees.length === 0) {
      setMissingPeople(true);
      return;
    }
    share.saveSettings({
      access,
      grantees: isPeople ? grantees : [],
      ...expiryChange(expiry),
    });
  };

  return (
    <>
      <Modal.Body className="flex flex-col gap-5">
        <Select
          className={inputVariants()}
          value={access}
          onChange={(key) => {
            if (isLinkAccess(key)) setAccess(key);
          }}
        >
          <Label>Who can open it</Label>
          <Select.Trigger>
            <GaiaSelectValue />
            <Select.Indicator />
          </Select.Trigger>
          <Select.Popover>
            <ListBox>
              {LINK_ACCESS_ORDER.map((level) => (
                <GaiaListBoxItem
                  key={level}
                  id={level}
                  textValue={LINK_ACCESS_OPTIONS[level].label}
                >
                  <div className="flex min-w-0 flex-col">
                    <Label>{LINK_ACCESS_OPTIONS[level].label}</Label>
                    <Description>
                      {LINK_ACCESS_OPTIONS[level].description}
                    </Description>
                  </div>
                </GaiaListBoxItem>
              ))}
            </ListBox>
          </Select.Popover>
        </Select>

        {access === "people" && (
          <GranteeEmailsInput
            emails={grantees}
            onEmailsChange={(emails) => {
              setGrantees(emails);
              setMissingPeople(false);
            }}
            isMissing={missingPeople}
          />
        )}

        {exceedsContent && (
          <div className="flex gap-2 rounded-xl bg-amber-400/10 p-3 text-sm text-amber-400">
            <Alert01Icon size={16} className="mt-0.5 shrink-0" />
            <span>
              This file can only be shown to "
              {LINK_ACCESS_OPTIONS[maxAccess].label}" or narrower. Anyone else
              who opens the link will see only its name and size.
            </span>
          </div>
        )}

        <RadioGroup
          orientation="horizontal"
          value={expiry}
          onChange={(value) => {
            if (isExpiryChoice(value)) setExpiry(value);
          }}
        >
          <Label>Expires</Label>
          <div className="flex flex-wrap gap-4">
            {expiryChoices.map((choice) => (
              <Radio key={choice.key} value={choice.key}>
                <Radio.Content>
                  <Radio.Control>
                    <Radio.Indicator />
                  </Radio.Control>
                  {choice.label}
                </Radio.Content>
              </Radio>
            ))}
          </div>
          {link && <Description>{describeExpiry(link.expires_at)}</Description>}
        </RadioGroup>

        {link && (
          <div className="flex flex-col gap-2 rounded-2xl bg-zinc-900 p-3">
            <InputGroup className={inputVariants({ size: "sm" })}>
              <InputGroup.Input aria-label="Link" readOnly value={link.url} />
              <InputGroup.Suffix>
                <GaiaButton
                  isIconOnly
                  size="sm"
                  variant="ghost"
                  aria-label="Copy link"
                  onPress={() => copyShortLink(link)}
                >
                  <Copy01Icon size={16} />
                </GaiaButton>
              </InputGroup.Suffix>
            </InputGroup>
            {confirmingRotate ? (
              <div className="flex flex-col gap-2">
                <span className="text-sm text-zinc-400">
                  The old link stops working for everyone who has it.
                </span>
                <div className="flex gap-2">
                  <GaiaButton
                    size="sm"
                    variant="danger-soft"
                    onPress={() => {
                      share.rotate();
                      setConfirmingRotate(false);
                    }}
                  >
                    Replace link
                  </GaiaButton>
                  <GaiaButton
                    size="sm"
                    variant="ghost"
                    onPress={() => setConfirmingRotate(false)}
                  >
                    Keep this link
                  </GaiaButton>
                </div>
              </div>
            ) : (
              <GaiaButton
                size="sm"
                variant="default-soft"
                className="self-start"
                isPending={share.isRotating}
                onPress={() => setConfirmingRotate(true)}
              >
                {share.isRotating ? null : <RefreshIcon size={16} />}
                Get a new link
              </GaiaButton>
            )}
          </div>
        )}
      </Modal.Body>
      <Modal.Footer>
        <GaiaButton variant="ghost" onPress={share.closeSettings}>
          Cancel
        </GaiaButton>
        <GaiaButton variant="primary" isPending={share.isSaving} onPress={save}>
          Save
        </GaiaButton>
      </Modal.Footer>
    </>
  );
}
