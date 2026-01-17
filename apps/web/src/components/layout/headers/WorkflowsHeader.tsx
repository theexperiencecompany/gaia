"use client";

import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { ZapIcon } from "@/icons";

export default function WorkflowsHeader() {
  return (
    <div className="flex w-full items-center justify-between">
      <HeaderTitle icon={<ZapIcon width={20} height={20} />} text="Workflows" />
    </div>
  );
}
