import Image from "next/image";
import { ReactNode } from "react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui";
import { useUser } from "@/features/auth/hooks/useUser";
import { cn } from "@/lib/utils";

export function SimpleChatBubbleUser({
  children,
  hideMobile = false,
  className = "",
  className2 = "",
}: {
  children: ReactNode;
  hideMobile?: boolean;
  className?: string;
  className2?: string;
}) {
  const user = useUser();

  if (hideMobile) return <></>;

  return (
    <div className={`mb-3 flex items-end justify-end gap-3 ${className}`}>
      <div
        className={`chat_bubble user whitespace-pre-wrap select-none ${className2}`}
      >
        {children}
      </div>
      <Avatar className="h-8 w-8 flex-shrink-0 rounded-full border-2 border-white/20">
        <AvatarImage src={user?.profilePicture} alt={user?.name || "User"} />
        <AvatarFallback className="bg-blue-500 text-xs text-white">
          {user?.name ? (
            user.name.charAt(0).toUpperCase()
          ) : (
            <Image
              src="/images/avatars/default.webp"
              width={32}
              height={32}
              alt="Default avatar"
              className="rounded-full"
            />
          )}
        </AvatarFallback>
      </Avatar>
    </div>
  );
}

export function SimpleChatBubbleBot({
  className,
  children,
  parentClassName,
}: {
  children: ReactNode;
  className?: string;
  parentClassName?: string;
}) {
  return (
    <div className={`relative mb-3 flex items-end gap-3 ${parentClassName}`}>
      <div className="relative z-[1] w-[35px]">
        <Image
          src="/images/logos/logo.webp"
          width={50}
          height={50}
          alt="GAIA"
          className="rounded-full"
        />
      </div>
      <div
        className={cn(
          "chat_bubble imessage-bubble imessage-from-them text-white",
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}
