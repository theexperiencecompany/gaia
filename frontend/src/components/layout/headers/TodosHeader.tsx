"use client";

import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { Task01Icon } from "@/components/shared/icons";
import { NotificationCenter } from "@/features/notification/components/NotificationCenter";
import TodoModal from "@/features/todo/components/TodoModal";
import { Tooltip } from "@heroui/react";

export default function TodosHeader() {
  return (
    <div className="flex w-full items-center justify-between">
      <HeaderTitle
        icon={<Task01Icon width={20} height={20} color={undefined} />}
        text="Todos"
      />

      <div className="relative z-[100] flex items-center">
        <Tooltip content="Create new todo">
          <div className="group/btn [&_svg]:!h-5 [&_svg]:!w-5 [&_svg]:!text-zinc-400 hover:[&_svg]:!text-primary">
            <TodoModal
              mode="add"
              buttonText=""
              buttonClassName="!p-1.5 !m-0 !bg-transparent !min-w-0 hover:!bg-[#00bbff]/20 data-[hover=true]:!bg-[#00bbff]/20 rounded-xl"
              onSuccess={() => {
                window.location.reload();
              }}
            />
          </div>
        </Tooltip>
        <NotificationCenter />
      </div>
    </div>
  );
}
