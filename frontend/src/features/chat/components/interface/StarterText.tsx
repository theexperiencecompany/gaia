import Image from "next/image";
import { useMemo } from "react";

import { useUser } from "@/features/auth/hooks/useUser";
import { getCompleteTimeBasedGreeting } from "@/utils/greetingUtils";

export default function StarterText() {
  const user = useUser();

  const greeting = useMemo(() => {
    return getCompleteTimeBasedGreeting(user?.name);
  }, [user?.name]);

  return (
    <>
      <div className="inline-flex flex-wrap items-center justify-center text-center font-medium">
        <div className="flex flex-col items-center">
          <div className="flex items-center gap-5 text-4xl">
            <Image
              alt="GAIA Logo"
              src="/images/logos/logo.webp"
              width={40}
              height={40}
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
    </>
  );
}
