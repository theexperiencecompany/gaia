"use client";

import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Radio, RadioGroup } from "@heroui/radio";
import { Flag02Icon } from "@icons";
import { Turnstile, type TurnstileInstance } from "@marsidev/react-turnstile";
import { ApiError } from "@shared/api";
import { useRef, useState } from "react";

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
      <Button
        size="sm"
        variant="flat"
        startContent={<Flag02Icon className="size-4" />}
        onPress={() => setIsOpen(true)}
      >
        Report
      </Button>
      <Modal isOpen={isOpen} onClose={() => setIsOpen(false)}>
        <ModalContent>
          {(onClose) => (
            <ReportForm slug={slug} label={label} onDone={onClose} />
          )}
        </ModalContent>
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
      <ModalHeader>Report this {label}</ModalHeader>
      <ModalBody>
        <RadioGroup
          aria-label="Why are you reporting this?"
          value={reason}
          onValueChange={(value) => setReason(value as ReportReason)}
        >
          {REPORT_REASONS.map((value) => (
            <Radio key={value} value={value}>
              {REPORT_REASON_LABELS[value]}
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
      </ModalBody>
      <ModalFooter>
        <Button variant="flat" onPress={onDone}>
          Cancel
        </Button>
        <Button
          color="danger"
          isDisabled={!reason}
          isLoading={isSending}
          onPress={send}
        >
          Send report
        </Button>
      </ModalFooter>
    </>
  );
}
