import { Button } from "@heroui/button";
import Image from "next/image";

import { useUser } from "@/features/auth/hooks/useUser";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import SettingsMenu from "@/features/settings/components/SettingsMenu";
import { ChevronsUpDown } from "@/icons";

import { Avatar, AvatarFallback, AvatarImage } from "../../ui/shadcn/avatar";

export default function UserContainer() {
  const user = useUser();
  const { data: subscriptionStatus } = useUserSubscriptionStatus();

  return (
    <SettingsMenu>
      <Button
        className="group/triggerbtn pointer-events-auto relative flex w-full flex-row justify-between gap-3 bg-transparent px-2 py-6! hover:bg-zinc-800"
        endContent={
          <ChevronsUpDown
            className="text-zinc-500 transition"
            width={20}
            height={20}
          />
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
            <span className="text-[11px] text-foreground-400">
              {subscriptionStatus?.is_subscribed ? "GAIA Pro" : "GAIA Free"}
            </span>
          </div>
        </div>
      </Button>
    </SettingsMenu>
  );
}
