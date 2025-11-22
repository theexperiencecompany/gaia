"use client";

import Link from "next/link";

import { RaisedButton } from "@/components/ui/raised-button";
import { posthog } from "@/lib";

export default function GetStartedButton({
  small_text = false,
  text = "Start for free",
}: {
  small_text?: boolean;
  text?: string;
}) {
  return (
    <div className="relative z-[2] flex flex-col items-center gap-4">
      <Link href={"/signup"}>
        <RaisedButton
          className="rounded-xl px-8 text-black! before:rounded-xl hover:scale-110"
          color="#00bbff"
          onClick={() => {
            posthog.capture("cta:get_started_clicked", {
              button_text: text,
              has_small_text: small_text,
            });
          }}
        >
          {text}
        </RaisedButton>
      </Link>

      {small_text && (
        <div className="text-xs font-light text-black">
          No credit card required. Free forever plan included.
        </div>
      )}
    </div>
  );
}
