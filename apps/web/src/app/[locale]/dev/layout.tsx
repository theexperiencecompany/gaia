import type { ReactNode } from "react";
import { HeroUIProvider } from "@/layouts/HeroUIProvider";

export default function DevLayout({ children }: { children: ReactNode }) {
  return <HeroUIProvider>{children}</HeroUIProvider>;
}
