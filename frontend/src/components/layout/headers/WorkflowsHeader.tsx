"use client";

import { Button } from "@heroui/button";
import { ExternalLink, ZapIcon } from "lucide-react";
import Link from "next/link";

import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";

interface WorkflowsHeaderProps {
  onCreateWorkflow: () => void;
}

export default function WorkflowsHeader({
  onCreateWorkflow,
}: WorkflowsHeaderProps) {
  return (
    <div className="flex w-full items-center justify-between">
      <HeaderTitle
        icon={<ZapIcon width={20} height={20} color={undefined} />}
        text="Workflows"
      />
      <div className="relative flex items-center gap-2">
        <Link href="/use-cases">
          <Button
            variant="light"
            className="text-zinc-400"
            endContent={<ExternalLink width={16} height={16} />}
          >
            Browse Use Cases
          </Button>
        </Link>
        <Button color="primary" onPress={onCreateWorkflow}>
          Create Workflow
        </Button>
      </div>
    </div>
  );
}
