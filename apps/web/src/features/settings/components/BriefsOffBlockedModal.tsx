"use client";

import { BRIEF_FREE_DELIVERIES, type BriefFreeDelivery } from "@gaia/shared";
import { Modal } from "@heroui/react";
import { useState } from "react";
import { modalVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { DeliverySegments } from "@/features/workflows/components/DeliverySegments";
import type { BriefsOffBlock } from "@/services/api/notifications";

interface BriefsOffBlockedModalProps {
  block: BriefsOffBlock | null;
  saving: boolean;
  onTurnOff: (deliveries: Record<string, BriefFreeDelivery>) => void;
  onCancel: () => void;
}

/**
 * Shown when turning briefs off was refused because workflows still deliver
 * to the brief. Each one gets a new delivery here; briefs turn off only once
 * none is left on the brief, and cancelling changes nothing.
 */
export function BriefsOffBlockedModal({
  block,
  saving,
  onTurnOff,
  onCancel,
}: BriefsOffBlockedModalProps) {
  return (
    <Modal
      isOpen={block !== null}
      onOpenChange={(nextOpen) => !nextOpen && onCancel()}
    >
      <Modal.Backdrop isDismissable={!saving}>
        <Modal.Container scroll="inside">
          <Modal.Dialog className={modalVariants({ size: "xl" })}>
            <Modal.CloseTrigger aria-label="Close" />
            {block && (
              <BriefsOffChoices
                block={block}
                saving={saving}
                onTurnOff={onTurnOff}
                onCancel={onCancel}
              />
            )}
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}

function BriefsOffChoices({
  block,
  saving,
  onTurnOff,
  onCancel,
}: BriefsOffBlockedModalProps & { block: BriefsOffBlock }) {
  const [choices, setChoices] = useState<Record<string, BriefFreeDelivery>>({});
  const unchosen = block.workflows.filter((w) => !choices[w.id]).length;

  const setAllToNow = () =>
    setChoices(
      Object.fromEntries(block.workflows.map((w) => [w.id, "now" as const])),
    );

  return (
    <>
      <Modal.Header>
        <div className="flex flex-col gap-1 pr-10">
          <Modal.Heading>{block.message}</Modal.Heading>
          <span className="text-sm font-normal text-zinc-400">
            With briefs off, their results would go nowhere. Choose where each
            one goes, then turn briefs off.
          </span>
        </div>
      </Modal.Header>
      <Modal.Body className="flex flex-col gap-3">
        <div className="flex justify-end">
          <GaiaButton
            size="sm"
            variant="default-soft"
            shape="md"
            onPress={setAllToNow}
            isDisabled={saving}
          >
            Set all to Tell me now
          </GaiaButton>
        </div>
        <ul className="flex flex-col gap-2">
          {block.workflows.map((workflow) => (
            <li
              key={workflow.id}
              className="flex flex-col gap-2 rounded-2xl bg-zinc-800 p-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
            >
              <span className="line-clamp-2 min-w-0 text-sm font-medium text-zinc-100">
                {workflow.title}
              </span>
              <DeliverySegments
                label={`Delivery for ${workflow.title}`}
                deliveries={BRIEF_FREE_DELIVERIES}
                value={choices[workflow.id] ?? null}
                onChange={(delivery) =>
                  setChoices((current) => ({
                    ...current,
                    [workflow.id]: delivery,
                  }))
                }
                isDisabled={() => saving}
                className="shrink-0 flex-row bg-zinc-900"
              />
            </li>
          ))}
        </ul>
      </Modal.Body>
      <Modal.Footer className="items-center">
        {unchosen > 0 && (
          <span className="mr-auto text-sm text-zinc-400">
            {unchosen} left to choose
          </span>
        )}
        <GaiaButton
          variant="ghost"
          shape="md"
          onPress={onCancel}
          isDisabled={saving}
        >
          Cancel
        </GaiaButton>
        <GaiaButton
          variant="primary"
          shape="md"
          isDisabled={unchosen > 0}
          isPending={saving}
          onPress={() => onTurnOff(choices)}
        >
          Turn off briefs
        </GaiaButton>
      </Modal.Footer>
    </>
  );
}
