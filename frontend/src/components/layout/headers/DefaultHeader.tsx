"use client";

import Link from "next/link";

import { Button } from "@/components/ui/shadcn/button";
import { NotificationCenter } from "@/features/notification/components/NotificationCenter";
import { ChatBubbleAddIcon } from "@/icons";

export default function DefaultHeader() {
  return (
    <>
      <div />
      <div className="flex flex-row flex-nowrap gap-2">
        <Link href={"/c"}>
          <Button
            aria-label="Create new chat"
            className={`group rounded-lg hover:bg-[#00bbff]/20`}
            size="icon"
            variant={"ghost"}
          >
            <ChatBubbleAddIcon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-all group-hover:text-primary" />
          </Button>
        </Link>
        <NotificationCenter />
      </div>
    </>
  );
}
