"use client";

import { Login02Icon, MessageMultiple02Icon } from "@icons";
import NumberFlow from "@number-flow/react";
import Link from "next/link";
import { Github, StarFilledIcon } from "@/components/shared/icons";
import { Button } from "@/components/ui/button";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { RaisedButton } from "../ui/raised-button";

interface NavbarActionsProps {
  isAuthenticated: boolean;
  stars: number;
  isStarsLoading: boolean;
}

export function NavbarActions({
  isAuthenticated,
  stars,
  isStarsLoading,
}: NavbarActionsProps) {
  const starsTiming = {
    duration: isStarsLoading ? 120 : 900,
    easing: isStarsLoading ? "linear" : "cubic-bezier(.2,.8,.2,1)",
  };

  return (
    <div className="group hidden items-center gap-3 sm:flex">
      <a
        href="https://github.com/theexperiencecompany/gaia"
        target="_blank"
        rel="noopener noreferrer"
        onClick={() => {
          trackEvent(ANALYTICS_EVENTS.NAVIGATION_GITHUB_CLICKED, {
            source: "navbar",
          });
        }}
      >
        <Button className="group rounded-xl border-0! bg-black/60 hover:bg-black/40 text-white">
          <div className="flex items-center">
            <Github className="mr-1 size-4 fill-white" />
            <span className="ml-1 lg:hidden">Star</span>
            <span className="ml-1 hidden lg:inline">GitHub</span>
          </div>
          <div className="flex items-center gap-1 text-sm">
            <StarFilledIcon className="relative top-px size-4 text-white group-hover:text-yellow-300" />
            <NumberFlow
              value={stars}
              className="font-medium text-white tabular-nums"
              transformTiming={starsTiming}
              spinTiming={starsTiming}
            />
          </div>
        </Button>
      </a>
      <Link href={isAuthenticated ? "/c" : "/signup"}>
        <RaisedButton
          size={"sm"}
          className="rounded-xl text-black!"
          color="#00bbff"
          onClick={() => {
            trackEvent(ANALYTICS_EVENTS.NAVIGATION_CTA_CLICKED, {
              is_logged_in: isAuthenticated,
              destination: isAuthenticated ? "/c" : "/signup",
            });
          }}
        >
          {isAuthenticated ? "Chat" : "Get Started"}
          {isAuthenticated ? (
            <MessageMultiple02Icon width={17} height={17} />
          ) : (
            <Login02Icon width={19} height={19} />
          )}
        </RaisedButton>
        {/* #1c1c1c */}
      </Link>
    </div>
  );
}
