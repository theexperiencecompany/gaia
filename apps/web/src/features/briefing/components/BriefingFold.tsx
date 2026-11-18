"use client";

import { ArrowExpand01Icon } from "@icons";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import {
  LETTER_CONTROL_PROPS,
  LetterModal,
  LetterSheet,
} from "@/components/shared/LetterModal";
import { LinkButton } from "@/components/shared/LinkButton";
import { LoadError } from "@/components/shared/LoadError";

import { briefingQuery } from "../api/briefingApi";
import { type BriefTriggerState, useOpenBrief } from "../hooks/useOpenBrief";
import { BRIEF_LETTER_WIDTH } from "../letterTokens";

import { briefPath, type FoldedBriefSummary } from "../utils/briefCard";
import { BriefingEdition, BriefingText } from "./BriefingEdition";
import { EditionUnfold } from "./EditionUnfold";

export interface BriefingFoldProps {
  briefingId: string;
  brief: FoldedBriefSummary;
  /** Draws the folded brief: a FoldedBriefCard, the chat's BriefLetter, a postmark's stamp. */
  children: (trigger: BriefTriggerState) => ReactNode;
}

/** A folded brief; pressing it unfolds the edition (or its text) above the page. */
export function BriefingFold({
  briefingId,
  brief,
  children,
}: BriefingFoldProps) {
  const { trigger, opened, origin, isOpen, close, retry, settle } =
    useOpenBrief(brief, briefingId);
  // The unfolding edition is a picture; a screen reader reads the letter's text, fetched alongside it.
  const { data: stored } = useQuery({
    ...briefingQuery(briefingId),
    enabled: opened?.kind === "edition",
  });
  const { headline } = brief;
  const fullBrief =
    opened && opened.kind !== "missing" ? briefPath(briefingId) : null;

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
          <>
            <EditionUnfold
              edition={opened.edition}
              alt={headline}
              origin={origin}
              onFolded={settle}
            />
            {stored && (
              <div className="sr-only">
                <BriefingText
                  payload={stored.payload}
                  uncomposed={stored.left_out.uncomposed}
                />
              </div>
            )}
          </>
        ) : (
          <LetterSheet
            style={{ width: BRIEF_LETTER_WIDTH }}
            className="rounded-2xl shadow-[0_32px_80px_-24px_rgba(0,0,0,0.75)]"
          >
            {opened?.kind === "text" ? (
              <BriefingEdition
                payload={opened.briefing.payload}
                leftOut={opened.briefing.left_out}
              />
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
