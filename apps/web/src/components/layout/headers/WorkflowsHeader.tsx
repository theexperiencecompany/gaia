"use client";

import { Button } from "@heroui/button";
import Link from "next/link";

import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { LinkSquare02Icon, ZapIcon } from "@/icons";

export default function WorkflowsHeader() {
  return (
    <div className="flex w-full items-center justify-between">
      <HeaderTitle icon={<ZapIcon width={20} height={20} />} text="Workflows" />
      <div className="relative flex items-center gap-2">
        <Link href="/use-cases">
          <Button
            variant="light"
            className="text-zinc-400"
            endContent={<LinkSquare02Icon width={16} height={16} />}
          >
            Browse Use Cases
          </Button>
        </Link>
      </div>
    </div>
  );
}
