import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import Image from "next/image";
import React from "react";
import { ChevronsDownUp, ChevronsUpDown } from "@/components/shared/icons";
import { useUser } from "@/features/auth/hooks/useUser";
import { paywallCopyFor } from "@/features/pricing/constants";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import SettingsMenu from "@/features/settings/components/SettingsMenu";

import { Avatar, AvatarFallback, AvatarImage } from "../../ui/avatar";

export default function UserContainer() {
  const user = useUser();
  const { isPaid, isUnknown, hasEverSubscribed } = useIsPaid();
  const [isOpen, setIsOpen] = React.useState(false);

  return (
    <SettingsMenu onOpenChange={setIsOpen}>
      <Button
        className="group/triggerbtn pointer-events-auto relative flex w-full flex-row justify-between gap-3 bg-transparent px-2 py-6! hover:bg-zinc-800"
        endContent={
          isOpen ? (
            <ChevronsDownUp
              className="text-zinc-500 transition"
              width={20}
              height={20}
            />
          ) : (
            <ChevronsUpDown
              className="text-zinc-500 transition"
              width={20}
              height={20}
            />
          )
        }
      >
        <div className="flex items-center gap-3">
          <Avatar className="size-7 rounded-full bg-black">
            <AvatarImage src={user?.profilePicture} alt="User Avatar" />
            <AvatarFallback>
              <Image
                src={"/images/avatars/default.webp"}
                width={30}
                height={30}
                alt="Default profile picture"
              />
            </AvatarFallback>
          </Avatar>
          <div className="flex flex-col items-start -space-y-0.5">
            <span className="text-sm">{user?.name}</span>
            {isUnknown ? (
              <Skeleton className="h-2.5 w-12 rounded-full" />
            ) : (
              <span className="text-[11px] text-foreground-400">
                {isPaid
                  ? "GAIA Pro"
                  : paywallCopyFor(hasEverSubscribed).planLabel}
              </span>
            )}
          </div>
        </div>
      </Button>
    </SettingsMenu>
  );
}
