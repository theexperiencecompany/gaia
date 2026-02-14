"use client";

import { ZapIcon } from "@icons";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";

export default function WorkflowsHeader() {
  return (
    <div className="flex w-full items-center justify-between">
      <HeaderTitle icon={<ZapIcon width={20} height={20} />} text="Workflows" />
    </div>
  );
}
