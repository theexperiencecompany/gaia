"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Radio, RadioGroup } from "@heroui/radio";
import { Select, SelectItem } from "@heroui/select";
import { Spinner } from "@heroui/spinner";
import { Alert01Icon, Copy01Icon, RefreshIcon } from "@icons";
import { useState } from "react";
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
      onClose={share.closeSettings}
      isDismissable={!share.isSaving}
      size="md"
      scrollBehavior="inside"
    >
      <ModalContent>
        <ModalHeader className="flex-col gap-1">
          <span>Share settings</span>
          <span className="text-sm font-normal text-zinc-400">
            Who can open this link, and for how long.
          </span>
        </ModalHeader>
        {share.link === undefined ? (
          <ModalBody className="items-center py-8">
            <Spinner size="sm" />
          </ModalBody>
        ) : (
          <ShareSettingsForm share={share} link={share.link} />
        )}
      </ModalContent>
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
      <ModalBody className="gap-5">
        <Select
          label="Who can open it"
          labelPlacement="outside"
          selectedKeys={[access]}
          disallowEmptySelection
          onSelectionChange={(keys) => {
            const [next] = Array.from(keys);
            if (isLinkAccess(next)) setAccess(next);
          }}
        >
          {LINK_ACCESS_ORDER.map((level) => (
            <SelectItem
              key={level}
              description={LINK_ACCESS_OPTIONS[level].description}
            >
              {LINK_ACCESS_OPTIONS[level].label}
            </SelectItem>
          ))}
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
          label="Expires"
          orientation="horizontal"
          value={expiry}
          onValueChange={(value) => {
            if (isExpiryChoice(value)) setExpiry(value);
          }}
          description={link ? describeExpiry(link.expires_at) : undefined}
        >
          {link?.expires_at && <Radio value="keep">Keep current</Radio>}
          {EXPIRY_PRESETS.map((preset) => (
            <Radio key={preset.key} value={preset.key}>
              {preset.label}
            </Radio>
          ))}
          <Radio value="never">Never</Radio>
        </RadioGroup>

        {link && (
          <div className="flex flex-col gap-2 rounded-2xl bg-zinc-900 p-3">
            <Input
              aria-label="Link"
              isReadOnly
              size="sm"
              value={link.url}
              endContent={
                <Button
                  isIconOnly
                  size="sm"
                  variant="light"
                  aria-label="Copy link"
                  onPress={() => copyShortLink(link)}
                >
                  <Copy01Icon size={16} />
                </Button>
              }
            />
            {confirmingRotate ? (
              <div className="flex flex-col gap-2">
                <span className="text-sm text-zinc-400">
                  The old link stops working for everyone who has it.
                </span>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    color="danger"
                    variant="flat"
                    onPress={() => {
                      share.rotate();
                      setConfirmingRotate(false);
                    }}
                  >
                    Replace link
                  </Button>
                  <Button
                    size="sm"
                    variant="light"
                    onPress={() => setConfirmingRotate(false)}
                  >
                    Keep this link
                  </Button>
                </div>
              </div>
            ) : (
              <Button
                size="sm"
                variant="flat"
                className="self-start"
                isLoading={share.isRotating}
                startContent={
                  share.isRotating ? undefined : <RefreshIcon size={16} />
                }
                onPress={() => setConfirmingRotate(true)}
              >
                Get a new link
              </Button>
            )}
          </div>
        )}
      </ModalBody>
      <ModalFooter>
        <Button variant="light" onPress={share.closeSettings}>
          Cancel
        </Button>
        <Button color="primary" isLoading={share.isSaving} onPress={save}>
          Save
        </Button>
      </ModalFooter>
    </>
  );
}
