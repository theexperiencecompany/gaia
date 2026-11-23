"use client";

import { Modal, Radio, RadioGroup } from "@heroui/react";
import { Flag02Icon } from "@icons";
import { Turnstile, type TurnstileInstance } from "@marsidev/react-turnstile";
import { ApiError } from "@shared/api";
import { useRef, useState } from "react";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { TURNSTILE_SITE_KEY } from "@/features/contact/constants";
import type { ReportReason } from "@/types/features/shortLinkTypes";

import { reportLink } from "../api/linkViewerApi";
import { REPORT_COPY, REPORT_REASON_LABELS } from "../constants";

const REPORT_REASONS = Object.keys(REPORT_REASON_LABELS) as ReportReason[];

interface ReportLinkButtonProps {
  slug: string;
  /** What the link points at, as a noun: "file", "brief". */
  label: string;
}

/** "Report" on a link page: a reason, a Turnstile check where the deployment has one, then the report. */
export function ReportLinkButton({ slug, label }: ReportLinkButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <>
      <GaiaButton
        size="sm"
        variant="default-soft"
        onPress={() => setIsOpen(true)}
      >
        <Flag02Icon className="size-4" />
        Report
      </GaiaButton>
      <Modal isOpen={isOpen} onOpenChange={setIsOpen}>
        <Modal.Backdrop>
          <Modal.Container>
            <Modal.Dialog>
              <Modal.CloseTrigger aria-label="Close" />
              <ReportForm
                slug={slug}
                label={label}
                onDone={() => setIsOpen(false)}
              />
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </>
  );
}

function ReportForm({
  slug,
  label,
  onDone,
}: ReportLinkButtonProps & { onDone: () => void }) {
  const [reason, setReason] = useState<ReportReason | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [verificationError, setVerificationError] = useState(false);
  const turnstileRef = useRef<TurnstileInstance>(null);

  /** A Turnstile token where the deployment checks one, null where it does not; undefined once verification failed. */
  const turnstileToken = async (): Promise<string | null | undefined> => {
    if (!TURNSTILE_SITE_KEY) return null;
    try {
      const turnstile = turnstileRef.current;
      if (!turnstile) throw new Error("Turnstile widget is not mounted");
      return await turnstile.getResponsePromise();
    } catch (error) {
      console.error("Turnstile did not produce a token:", error);
      setVerificationError(true);
      return undefined;
    }
  };

  const send = async () => {
    if (!reason) return;
    setIsSending(true);
    try {
      const token = await turnstileToken();
      if (token === undefined) return;
      await reportLink(slug, reason, token);
      onDone();
    } catch (error) {
      // The API client already toasted the failure; the form stays open to retry.
      if (!(error instanceof ApiError)) throw error;
    } finally {
      setIsSending(false);
      // Tokens are single-use.
      turnstileRef.current?.reset();
    }
  };

  return (
    <>
      <Modal.Header>
        <Modal.Heading>Report this {label}</Modal.Heading>
      </Modal.Header>
      <Modal.Body className="flex flex-col gap-3">
        <RadioGroup
          aria-label="Why are you reporting this?"
          value={reason}
          onChange={(value) => setReason(value as ReportReason)}
        >
          {REPORT_REASONS.map((value) => (
            <Radio key={value} value={value}>
              <Radio.Content>
                <Radio.Control>
                  <Radio.Indicator />
                </Radio.Control>
                {REPORT_REASON_LABELS[value]}
              </Radio.Content>
            </Radio>
          ))}
        </RadioGroup>
        {TURNSTILE_SITE_KEY && (
          <Turnstile
            ref={turnstileRef}
            siteKey={TURNSTILE_SITE_KEY}
            options={{ appearance: "interaction-only", theme: "dark" }}
            onError={() => setVerificationError(true)}
            onSuccess={() => setVerificationError(false)}
          />
        )}
        {verificationError && (
          <p role="alert" className="text-sm text-danger">
            {REPORT_COPY.verificationFailed}
          </p>
        )}
      </Modal.Body>
      <Modal.Footer>
        <GaiaButton variant="default-soft" onPress={onDone}>
          Cancel
        </GaiaButton>
        <GaiaButton
          variant="danger"
          isDisabled={!reason}
          isPending={isSending}
          onPress={send}
        >
          Send report
        </GaiaButton>
      </Modal.Footer>
    </>
  );
}
