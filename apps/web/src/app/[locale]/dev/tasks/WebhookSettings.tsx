"use client";

import { InputGroup } from "@heroui/react";
import { Copy01Icon, Tick02Icon } from "@icons";
import { useState } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { toneVariants } from "@/components/shared/tone";
import { copyText } from "@/lib/clipboard";
import PickMenu from "./PickMenu";
import type { TaskWebhook, WebhookSigning } from "./taskModel";
import { Field, TextAction } from "./WhenParts";
import { ago } from "./watchModel";
import { WEBHOOK_BASE } from "./whenModel";

const SIGNING: { id: WebhookSigning; label: string }[] = [
  { id: "none", label: "None" },
  { id: "secret", label: "Shared secret" },
  { id: "stripe", label: "Stripe" },
  { id: "github", label: "GitHub" },
];

/** How long a copy shows its tick. */
const COPIED_MS = 1500;

/** A secret GAIA makes for the sender to sign with; Stripe makes its own. */
const makeSecret = () => `gaia_${crypto.randomUUID().replaceAll("-", "")}`;

/** A read-only value with a copy button at its end, on the editor's 36px field. */
function CopyField({
  label,
  value,
  isMono = false,
}: {
  label: string;
  value: string;
  isMono?: boolean;
}) {
  const [isCopied, setIsCopied] = useState(false);
  return (
    <InputGroup
      className={inputVariants({ variant: "sunken", className: "w-full" })}
    >
      <InputGroup.Input
        aria-label={label}
        readOnly
        value={value}
        onFocus={(event) => event.target.select()}
        className={toneVariants({
          tone: "bright",
          className: isMono ? "font-mono text-[13px]" : "text-sm",
        })}
      />
      <InputGroup.Suffix>
        <GaiaButton
          isIconOnly
          size="sm"
          variant="raised-ghost"
          tone="muted"
          hoverTone="bright"
          aria-label={`Copy ${label.toLowerCase()}`}
          onPress={async () => {
            await copyText(value);
            setIsCopied(true);
            setTimeout(() => setIsCopied(false), COPIED_MS);
          }}
          className="size-7 min-w-7"
        >
          {isCopied ? (
            <Tick02Icon className="size-4" />
          ) : (
            <Copy01Icon className="size-4" />
          )}
        </GaiaButton>
      </InputGroup.Suffix>
    </InputGroup>
  );
}

/**
 * The task's own webhook: the link another app sends to, how GAIA checks a
 * delivery is really from it, and a secret that is shown once.
 */
export default function WebhookSettings({
  webhook,
  onChange,
}: {
  webhook: TaskWebhook;
  onChange: (webhook: TaskWebhook) => void;
}) {
  // A secret shown in this sitting; the stored copy is dropped once it is shown.
  const [shown, setShown] = useState<string>();
  const makes = webhook.signing === "secret" || webhook.signing === "github";
  const choose = (signing: WebhookSigning) => {
    setShown(undefined);
    onChange({
      ...webhook,
      signing,
      secret:
        signing === "secret" || signing === "github" ? makeSecret() : undefined,
    });
  };
  const reveal = () => {
    setShown(webhook.secret);
    onChange({ ...webhook, secret: undefined });
  };

  return (
    <div className="space-y-2">
      <div>
        <p className="px-1 pb-1.5 text-[13px] text-zinc-500">
          This task's link
        </p>
        <CopyField label="Link" value={`${WEBHOOK_BASE}${webhook.id}`} />
        <p className="px-1 pt-1.5 text-xs text-zinc-500">
          {webhook.lastReceived
            ? `Last received ${ago(webhook.lastReceived)}.`
            : "Paste it where the other app asks for a webhook URL."}
        </p>
      </div>
      <Field label="Signature">
        <PickMenu
          label="Signature"
          summary={
            SIGNING.find((item) => item.id === webhook.signing)?.label ?? ""
          }
          options={SIGNING}
          selected={[webhook.signing]}
          isMultiple={false}
          onPick={(id) => choose(id as WebhookSigning)}
        />
      </Field>
      {webhook.signing === "stripe" && (
        <InputGroup
          className={inputVariants({ variant: "sunken", className: "w-full" })}
        >
          <InputGroup.Input
            aria-label="Stripe signing secret"
            type="password"
            value={webhook.secret ?? ""}
            onChange={(event) =>
              onChange({ ...webhook, secret: event.target.value })
            }
            placeholder="Paste Stripe's signing secret"
            className={inputVariants({
              placeholder: "subtle",
              className: toneVariants({ tone: "white", className: "text-sm" }),
            })}
          />
        </InputGroup>
      )}
      {makes && shown && <CopyField label="Secret" value={shown} isMono />}
      {makes && !shown && webhook.secret && (
        <Field label="Secret">
          <GaiaButton
            size="sm"
            variant="sunken"
            shape="md"
            tone="strong"
            inset="tight"
            onPress={reveal}
            className="h-9 w-44 min-w-0 justify-start text-sm"
          >
            Show it once
          </GaiaButton>
        </Field>
      )}
      {makes && !shown && !webhook.secret && (
        <Field label="Secret">
          <TextAction
            onPress={() => onChange({ ...webhook, secret: makeSecret() })}
          >
            Hidden. Make a new one
          </TextAction>
        </Field>
      )}
      {makes && shown && (
        <p className="px-1 text-xs text-zinc-500">
          {webhook.signing === "github"
            ? "Paste it into the webhook's Secret in GitHub. GAIA won't show it again."
            : "Give it to the sender. GAIA won't show it again."}
        </p>
      )}
    </div>
  );
}
