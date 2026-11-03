"use client";

import { Button } from "@heroui/button";
import { SquareLock01Icon } from "@icons";
import Image from "next/image";
import { RaisedButton } from "@/components/ui/raised-button";
import { ValueHeadline } from "./ValueHeadline";

interface ConnectGateProps {
  logoSrc: string;
  logoAlt: string;
  headline: string;
  line: string;
  connectLabel: string;
  /** What the permission does and does not allow, said before they grant it. */
  scopeNote: string;
  onConnect: () => void;
  onSkip: () => void;
}

/** The ask before a live run: one permission, what it allows, and a way past it. */
export function ConnectGate({
  logoSrc,
  logoAlt,
  headline,
  line,
  connectLabel,
  scopeNote,
  onConnect,
  onSkip,
}: ConnectGateProps) {
  return (
    <div className="flex flex-1 flex-col justify-center gap-8 @max-md:justify-start @max-md:pt-6">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-zinc-800">
        <Image
          src={logoSrc}
          alt={logoAlt}
          width={30}
          height={30}
          className="h-7 w-7 object-contain"
        />
      </div>
      <ValueHeadline headline={headline} line={line} />
      <div className="flex flex-col items-start gap-3 @max-md:mt-auto @max-md:items-stretch">
        <RaisedButton
          className="w-full max-w-sm @max-md:max-w-none"
          color="#00bbff"
          size="lg"
          onClick={onConnect}
        >
          {connectLabel}
        </RaisedButton>
        <p className="flex items-center gap-1.5 text-[13px] text-zinc-500">
          <SquareLock01Icon className="h-3.5 w-3.5 shrink-0" />
          {scopeNote}
        </p>
        <Button
          size="sm"
          variant="light"
          className="-ml-3 text-zinc-500 @max-md:ml-0"
          onPress={onSkip}
        >
          Skip, just show me the price
        </Button>
      </div>
    </div>
  );
}
