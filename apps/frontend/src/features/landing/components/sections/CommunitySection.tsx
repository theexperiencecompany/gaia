import Link from "next/link";
import React from "react";

import { SOCIAL_LINKS } from "./FinalSection";

export default function CommunitySection() {
  return (
    <div className="flex w-full items-center justify-center gap-5 py-4">
      <div className="mx-auto grid w-full max-w-7xl grid-cols-4 gap-6">
        {SOCIAL_LINKS.map(
          ({ href, ariaLabel, icon, label, username, color, description }) => {
            return (
              <Link
                key={href}
                href={href}
                aria-label={ariaLabel}
                className={`flex justify-start p-4 transition ${color} group w-full flex-row items-center gap-4 rounded-3xl bg-zinc-900 hover:bg-zinc-800`}
              >
                <div
                  className="flex items-center justify-center rounded-2xl border-t-1 border-r-1 border-white/30 p-2 transition group-hover:scale-110 group-hover:-rotate-8"
                  style={{ backgroundColor: color }}
                >
                  {icon &&
                    React.cloneElement(icon, {
                      className: "",
                      width: 40,
                      height: 40,
                      color: "",
                    })}
                </div>
                <div className="flex flex-col items-start justify-center">
                  <div className="text-lg font-semibold">
                    {username || label}
                  </div>
                  <div className="text-sm text-zinc-400">{description}</div>
                </div>
              </Link>
            );
          },
        )}
      </div>
    </div>
  );
}
