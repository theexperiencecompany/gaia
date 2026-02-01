"use client";

import Link from "next/link";
import { ChevronRight } from "@/components";
import { RaisedButton } from "@/components/ui/raised-button";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

export default function GetStartedButton({
  small_text = false,
  text = "Get Started",
}: {
  small_text?: boolean;
  text?: string;
}) {
  return (
    <div className="relative z-2 flex flex-col items-center gap-4 group">
      <Link href={"/signup"}>
        <RaisedButton
          className="rounded-xl px-1 text-black! before:rounded-xl hover:pl-2 duration-400 ease-out group shadow-black"
          color="#00bbff"
          onClick={() => {
            trackEvent(ANALYTICS_EVENTS.CTA_GET_STARTED_CLICKED, {
              button_text: text,
              has_small_text: small_text,
            });
          }}
        >
          <span className="group-hover:translate-x-1 translate-x-3 transition ease-out duration-300">
            {text}
          </span>
          <ChevronRight
            width={19}
            height={19}
            className="group-hover:translate-x-0 transition translate-x-9 ease-out duration-300"
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
