"use client";

import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";

import { GaiaNative } from "./versions/GaiaNative";

export default function ReferralDemoBody() {
  return (
    <LazyMotionProvider>
      <div className="h-full min-h-0 overflow-y-auto bg-[#111111]">
        <GaiaNative />
      </div>
    </LazyMotionProvider>
  );
}
