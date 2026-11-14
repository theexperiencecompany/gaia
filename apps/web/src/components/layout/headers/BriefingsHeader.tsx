"use client";

import { News01Icon } from "@icons";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";

export default function BriefingsHeader() {
  return (
    <div className="flex w-full items-center">
      <HeaderTitle
        icon={<News01Icon width={20} height={20} />}
        text="Briefings"
      />
    </div>
  );
}
