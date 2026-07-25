"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Chip } from "@heroui/chip";
import { ShieldIcon } from "@icons";
import {
  type ApprovalRequestData,
  type ApprovalStatus,
  approvalOutcomeLabel,
} from "@shared/chat";

interface ApprovalReceiptsProps {
  items: ApprovalRequestData[];
}

type ChipColor = "success" | "danger" | "warning" | "default";

const OUTCOME: Record<ApprovalStatus, { label: string; color: ChipColor }> = {
  auto_approved: { label: "Ran automatically", color: "success" },
  approved: { label: "Approved", color: "success" },
  denied: { label: "Declined", color: "danger" },
  timeout: { label: "Expired", color: "warning" },
  abandoned: { label: "Dropped", color: "default" },
  pending: { label: "Pending", color: "warning" },
};

/**
 * Every action that needed approval this run, decided — including the ones auto mode
 * ran without asking, with the reason it judged them safe. Collapsed by default: it is
 * a receipt, not a request, so it should be checkable without being in the way.
 */
export const ApprovalReceipts = ({ items }: ApprovalReceiptsProps) => {
  if (items.length === 0) return null;

  const autoRan = items.filter((i) => i.status === "auto_approved").length;

  return (
    <div className="w-full max-w-md rounded-2xl bg-zinc-800 px-4 text-white">
      <Accordion isCompact className="px-0">
        <AccordionItem
          key="receipts"
          aria-label="Actions that needed approval"
          classNames={{ trigger: "py-3", content: "pb-3 pt-0" }}
          startContent={
            <ShieldIcon width={16} className="shrink-0 text-zinc-400" />
          }
          title={
            <span className="text-sm text-zinc-300">
              {items.length === 1 ? "1 action" : `${items.length} actions`}
              {autoRan > 0 && (
                <span className="text-zinc-500">
                  <span className="mx-1.5 inline-block size-1 rounded-full bg-zinc-600 align-middle" />
                  {autoRan} ran automatically
                </span>
              )}
            </span>
          }
        >
          <div className="space-y-2">
            {items.map((item) => {
              const outcome = OUTCOME[item.status];
              return (
                <div
                  key={item.approval_id}
                  className="rounded-2xl bg-zinc-900 p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="min-w-0 flex-1 truncate text-xs text-zinc-200">
                      {item.summary}
                    </span>
                    <Chip size="sm" variant="flat" color={outcome.color}>
                      {outcome.label}
                    </Chip>
                  </div>
                  <p className="mt-1.5 text-xs text-zinc-500">
                    {approvalOutcomeLabel(item)}
                  </p>
                </div>
              );
            })}
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
};
