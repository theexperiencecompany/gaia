"use client";

import type { ReactNode } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { Link } from "@/i18n/navigation";
import { track } from "@/lib/analytics";

export default function GetStartedButton({
  small_text = false,
  text = "Get Started",
  btnColor = "#00bbff",
  classname = "text-black!",
  href = "/signup",
}: {
  small_text?: boolean;
  text?: ReactNode;
  btnColor?: string;
  classname?: string;
  href?: string;
}) {
  return (
    <div className="relative z-2 flex flex-col items-center gap-4 group">
      <Link href={href}>
        <RaisedButton
          className={`rounded-xl ${classname} before:rounded-xl duration-400 ease-out group shadow-black hover:scale-110`}
          color={btnColor}
          onClick={() => {
            track("cta:get_started_clicked", {
              has_small_text: small_text,
            });
          }}
        >
          <span className="px-3">{text}</span>
        </RaisedButton>
      </Link>

      {small_text && (
        <div className="text-xs font-light text-black">
          Secure payment · Cancel anytime.
        </div>
      )}
    </div>
  );
}
