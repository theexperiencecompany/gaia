"use client";

import { ArrowExpand01Icon } from "@icons";
import type { ReactNode } from "react";

import {
  LETTER_CONTROL_PROPS,
  LetterModal,
  LetterSheet,
} from "@/components/shared/LetterModal";
import { LinkButton } from "@/components/shared/LinkButton";
import { LoadError } from "@/components/shared/LoadError";

import { BRIEF_LETTER_WIDTH } from "../constants";
import {
  type BriefSource,
  type BriefTriggerState,
  useOpenBrief,
} from "../hooks/useOpenBrief";

import { briefPath, type FoldedBriefSummary } from "../utils/briefCard";
import { BriefingEdition } from "./BriefingEdition";
import { EditionUnfold } from "./EditionUnfold";

export type BriefingFoldProps = BriefSource & {
  brief: FoldedBriefSummary;
  /** Draws the folded brief: a FoldedBriefCard, the chat's BriefLetter, a postmark's stamp. */
  children: (trigger: BriefTriggerState) => ReactNode;
};

/** A folded brief; pressing it unfolds the edition (or its text) above the page. */
export function BriefingFold({
  brief,
  children,
  ...source
}: BriefingFoldProps) {
  const { trigger, opened, origin, isOpen, close, retry, settle } =
    useOpenBrief(brief, source);
  const { headline } = brief;
  const fullBrief =
    source.briefingId && opened && opened.kind !== "missing"
      ? briefPath(source.briefingId)
      : null;

  return (
    <>
      {children(trigger)}

      <LetterModal
        isOpen={isOpen}
        onClose={close}
        ariaLabel={headline}
        presentation="floating"
        actions={
          fullBrief && (
            <LinkButton
              {...LETTER_CONTROL_PROPS}
              href={fullBrief}
              className="font-medium"
            >
              <ArrowExpand01Icon className="size-4" />
              Open full brief
            </LinkButton>
          )
        }
      >
        {opened?.kind === "edition" ? (
          <EditionUnfold
            edition={opened.edition}
            alt={headline}
            origin={origin}
            onFolded={settle}
          />
        ) : (
          <LetterSheet
            style={{ width: BRIEF_LETTER_WIDTH }}
            className="rounded-2xl shadow-[0_32px_80px_-24px_rgba(0,0,0,0.75)]"
          >
            {opened?.kind === "text" ? (
              <BriefingEdition payload={opened.payload} />
            ) : opened?.kind === "failed" ? (
              <LoadError
                className="bg-zinc-800"
                title="Couldn't load this brief"
                description="It's still in your briefings. This letter just couldn't reach it."
                onRetry={retry}
              />
            ) : (
              <p className="rounded-2xl bg-zinc-800 p-4 text-sm text-zinc-400">
                This brief isn&apos;t available anymore.
              </p>
            )}
          </LetterSheet>
        )}
      </LetterModal>
    </>
  );
}
