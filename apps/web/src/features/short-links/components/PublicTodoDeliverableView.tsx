import { Chip } from "@heroui/chip";
import { CheckmarkCircle02Icon } from "@icons";

import { RichContentRenderer } from "@/features/chat/components/interface/RichContentRenderer";
import type { PublicTodoDeliverable } from "@/types/features/shortLinkTypes";

export function PublicTodoDeliverableView({
  view,
}: {
  view: PublicTodoDeliverable;
}) {
  return (
    <article className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        {view.completed && (
          <Chip
            size="sm"
            color="success"
            variant="flat"
            radius="sm"
            startContent={<CheckmarkCircle02Icon className="h-3 w-3" />}
          >
            Done
          </Chip>
        )}
        <h1 className="text-2xl font-medium text-white">{view.title}</h1>
      </div>
      {view.content ? (
        <RichContentRenderer content={view.content} className="text-base" />
      ) : (
        <p className="py-16 text-center text-sm text-zinc-500">
          Nothing has been written here yet.
        </p>
      )}
    </article>
  );
}
