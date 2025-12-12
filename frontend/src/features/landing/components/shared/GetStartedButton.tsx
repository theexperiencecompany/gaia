"use client";

import Link from "next/link";
import { ChevronRight, Login02Icon } from "@/components";
import { RaisedButton } from "@/components/ui/raised-button";
import { posthog } from "@/lib";

export default function GetStartedButton({
  small_text = false,
  text = "Get Started",
}: {
  small_text?: boolean;
  text?: string;
}) {
  return (
    <div className="relative z-[2] flex flex-col items-center gap-4 group">
      <Link href={"/signup"}>
        <RaisedButton
          className="rounded-xl px-4 text-black! before:rounded-xl hover:scale-110 group"
          color="#00bbff"
          onClick={() => {
            posthog.capture("cta:get_started_clicked", {
              button_text: text,
              has_small_text: small_text,
            });
          }}
        >
          <span className="group-hover:-translate-x-0 translate-x-3 transition ease-out duration-300">
            {text}
          </span>
          <ChevronRight
            width={19}
            height={19}
            className="group-hover:-translate-x-0 transition translate-x-9 ease-out duration-300"
          />
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
