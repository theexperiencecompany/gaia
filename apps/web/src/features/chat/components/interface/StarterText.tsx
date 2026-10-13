import { getCompleteTimeBasedGreeting } from "@shared/utils";
import Image from "next/image";
import { useMemo } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";

export default function StarterText() {
  const user = useCurrentUser();

  const greeting = useMemo(() => {
    return getCompleteTimeBasedGreeting(user?.name);
  }, [user?.name]);

  return (
    <div className="inline-flex flex-wrap items-center justify-center text-center font-medium">
      <div className="flex flex-col items-center">
        <div className="flex items-center gap-5 text-4xl">
          <Image
            alt="GAIA Logo"
            src="/images/logos/logo.webp"
            width={40}
            height={40}
            className="hidden sm:block"
          />
          <span
            suppressHydrationWarning
            className="transition-opacity duration-300"
          >
            {greeting}
          </span>
        </div>
      </div>
    </div>
  );
}
