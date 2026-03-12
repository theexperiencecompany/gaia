"use client";

import type { ReactNode } from "react";

import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import { HeroUIProvider } from "@/layouts/HeroUIProvider";
import QueryProvider from "@/layouts/QueryProvider";

export default function RecordingLayout({ children }: { children: ReactNode }) {
  return (
    <HeroUIProvider>
      <LazyMotionProvider>
        <QueryProvider>{children}</QueryProvider>
      </LazyMotionProvider>
    </HeroUIProvider>
  );
}
