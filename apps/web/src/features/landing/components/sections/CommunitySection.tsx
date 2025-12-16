import Link from "next/link";
import React from "react";

import { RaisedButton } from "@/components/ui/raised-button";

import { SOCIAL_LINKS } from "./FinalSection";

export default function CommunitySection() {
  return (
    <section className="w-full px-4 py-16 sm:px-6">
      <div className="mx-auto grid w-full max-w-4xl grid-cols-1 items-center gap-8 md:grid-cols-2">
        {/* Left Column - Title & Description */}
        <div className="flex flex-col gap-3">
          <h2 className="text-3xl font-medium text-white sm:text-4xl">
            Join the Community
          </h2>
          <p className="max-w-md text-zinc-400">
            Connect with thousands of users, get help, share feedback, and stay
            updated on the latest features.
          </p>
        </div>

        {/* Right Column - Social Buttons 2x2 Grid */}
        <div className="grid grid-cols-2 gap-3 w-fit ml-auto">
          {SOCIAL_LINKS.map(({ href, ariaLabel, icon, label, buttonProps }) => (
            <Link
              key={href}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={ariaLabel}
            >
              <RaisedButton
                color={buttonProps.color}
                className={`flex h-auto w-40 flex-row items-center justify-center gap-2  ${label === "GitHub" ? "text-white" : "text-black!"}`}
              >
                {icon &&
                  React.cloneElement(icon, {
                    width: 22,
                    height: 22,
                  })}
                <span className="text-sm font-medium">{label}</span>
              </RaisedButton>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
