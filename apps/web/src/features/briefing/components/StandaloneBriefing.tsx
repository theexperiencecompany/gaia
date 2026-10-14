"use client";

import { Button } from "@heroui/button";
import { ArrowLeft01Icon } from "@icons";
import type { BriefingModel } from "@shared/api/generated";
import Link from "next/link";

import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";

import { BriefingEdition } from "./BriefingEdition";

export interface StandaloneBriefingProps {
  briefing: Pick<BriefingModel, "payload" | "edition_image_url">;
}

/**
 * A brief on its own full page, outside the app shell: opened from the email image,
 * the chat link or the Briefings list. Signed-in readers get a way back to their chats.
 */
export function StandaloneBriefing({ briefing }: StandaloneBriefingProps) {
  const { userId } = useCurrentUser();
  return (
    <main className="min-h-screen w-full bg-primary-bg px-4 py-6">
      <div className="mx-auto w-full max-w-3xl space-y-4">
        {userId && (
          <Button
            as={Link}
            href="/c"
            variant="light"
            size="sm"
            startContent={<ArrowLeft01Icon className="size-4" />}
          >
            Back to chats
          </Button>
        )}
        <BriefingEdition
          payload={briefing.payload}
          imageUrl={briefing.edition_image_url}
        />
      </div>
    </main>
  );
}
