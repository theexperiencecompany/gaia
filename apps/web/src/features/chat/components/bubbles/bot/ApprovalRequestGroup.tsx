import type { ApprovalRequestData } from "@shared/chat";
import ApprovalRequestSection from "./ApprovalRequestSection";

interface ApprovalRequestGroupProps {
  items: ApprovalRequestData[];
}

/**
 * Only pending approvals are shown — a settled one is removed entirely (nobody
 * acts on a decided card, and the assistant's reply already reflects it). A
 * single pending card renders on its own; several sit side by side so a run
 * needing many decisions stays compact.
 */
export default function ApprovalRequestGroup({
  items,
}: ApprovalRequestGroupProps) {
  const pending = items.filter((i) => i.status === "pending");
  if (pending.length === 0) return null;
  if (pending.length === 1) return <ApprovalRequestSection data={pending[0]} />;

  return (
    <div className="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
      {pending.map((item) => (
        <ApprovalRequestSection key={item.approval_id} data={item} />
      ))}
    </div>
  );
}
