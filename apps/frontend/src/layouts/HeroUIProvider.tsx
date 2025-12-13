// app/HeroUIProvider.tsx
"use client";

import { HeroUIProvider as HeroUIProviderComponent } from "@heroui/system";
import { useRouter } from "next/navigation";

// Only if using TypeScript
declare module "@react-types/shared" {
  interface RouterConfig {
    routerOptions: NonNullable<
      Parameters<ReturnType<typeof useRouter>["push"]>[1]
    >;
  }
}

export function HeroUIProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  return (
    <HeroUIProviderComponent navigate={router.push}>
      {children}
    </HeroUIProviderComponent>
  );
}
