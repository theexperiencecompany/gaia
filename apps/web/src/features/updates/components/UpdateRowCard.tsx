import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Alert02Icon, CheckmarkCircle02Icon, Clock01Icon } from "@icons";
import type { UpdateOutcome, UpdateRow } from "@shared/api/generated";
import Link from "next/link";
import type { ReactNode } from "react";
import { SUBJECT_KIND_LABELS } from "../constants";
import {
  updateBody,
  updateStatusLabel,
  updateTime,
} from "../utils/updateStatus";

const OUTCOME_ICONS: Record<UpdateOutcome, ReactNode> = {
  done: <CheckmarkCircle02Icon className="size-5 text-success" />,
  needs_you: <Alert02Icon className="size-5 text-warning" />,
  failed: <Alert02Icon className="size-5 text-danger" />,
};

interface UpdateRowCardProps {
  row: UpdateRow;
}

export function UpdateRowCard({ row }: UpdateRowCardProps) {
  return (
    <article className="flex w-full items-start gap-3 rounded-2xl bg-zinc-900 p-4">
      <div className="mt-0.5 shrink-0">
        {row.state === "held" ? (
          <Clock01Icon className="size-5 text-zinc-400" />
        ) : (
          OUTCOME_ICONS[row.outcome]
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="truncate text-sm font-medium text-zinc-100">
            {row.subject_label}
          </h3>
          <Chip size="sm" variant="flat">
            {SUBJECT_KIND_LABELS[row.subject_kind]}
          </Chip>
        </div>

        <p className="my-1 line-clamp-4 text-sm font-light whitespace-pre-line text-zinc-400">
          {updateBody(row)}
        </p>

        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span suppressHydrationWarning>{updateTime(row)}</span>
          <Chip size="sm" variant="flat">
            {updateStatusLabel(row)}
          </Chip>
        </div>
      </div>

      {row.conversation_id && (
        <Button
          as={Link}
          href={`/c/${row.conversation_id}`}
          size="sm"
          variant="flat"
          className="shrink-0"
        >
          Open
        </Button>
      )}
    </article>
  );
}
