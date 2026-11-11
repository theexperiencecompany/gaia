"use client";

import { BRIEF_FREE_DELIVERIES, type BriefFreeDelivery } from "@gaia/shared";
import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { useState } from "react";
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
      onClose={onCancel}
      isDismissable={!saving}
      size="xl"
      scrollBehavior="inside"
    >
      <ModalContent>
        {block && (
          <BriefsOffChoices
            block={block}
            saving={saving}
            onTurnOff={onTurnOff}
            onCancel={onCancel}
          />
        )}
      </ModalContent>
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
      <ModalHeader className="flex-col gap-1 pr-10">
        <span>{block.message}</span>
        <span className="text-sm font-normal text-zinc-400">
          With briefs off, their results would go nowhere. Choose where each one
          goes, then turn briefs off.
        </span>
      </ModalHeader>
      <ModalBody className="gap-3">
        <div className="flex justify-end">
          <Button
            size="sm"
            variant="flat"
            radius="lg"
            onPress={setAllToNow}
            isDisabled={saving}
          >
            Set all to Tell me now
          </Button>
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
      </ModalBody>
      <ModalFooter className="items-center">
        {unchosen > 0 && (
          <span className="mr-auto text-sm text-zinc-400">
            {unchosen} left to choose
          </span>
        )}
        <Button
          variant="light"
          radius="lg"
          onPress={onCancel}
          isDisabled={saving}
        >
          Cancel
        </Button>
        <Button
          color="primary"
          radius="lg"
          isDisabled={unchosen > 0}
          isLoading={saving}
          onPress={() => onTurnOff(choices)}
        >
          Turn off briefs
        </Button>
      </ModalFooter>
    </>
  );
}
