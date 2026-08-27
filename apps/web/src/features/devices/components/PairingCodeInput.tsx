"use client";

import {
  InputOTP,
  InputOTPGroup,
  InputOTPSeparator,
  InputOTPSlot,
} from "@/components/ui/input-otp";
import {
  PAIRING_CODE_GROUP_LENGTH,
  PAIRING_CODE_LENGTH,
  PAIRING_CODE_PATTERN,
} from "../constants";

interface PairingCodeInputProps {
  /** The code without its separator, e.g. "ABCD2345". */
  value: string;
  onChange: (value: string) => void;
  onComplete: (value: string) => void;
  isDisabled: boolean;
}

const SLOT_INDEXES = Array.from(
  { length: PAIRING_CODE_LENGTH },
  (_, index) => index,
);
const FIRST_GROUP = SLOT_INDEXES.slice(0, PAIRING_CODE_GROUP_LENGTH);
const SECOND_GROUP = SLOT_INDEXES.slice(PAIRING_CODE_GROUP_LENGTH);

const SLOT_CLASSNAME =
  "size-11 rounded-xl border-0 bg-zinc-900 font-mono text-base font-medium text-zinc-100 shadow-none transition-[background-color,box-shadow] first:rounded-xl first:border-l-0 last:rounded-xl data-[active=true]:bg-zinc-800 data-[active=true]:ring-2 data-[active=true]:ring-primary/70";

export function PairingCodeInput({
  value,
  onChange,
  onComplete,
  isDisabled,
}: PairingCodeInputProps) {
  return (
    <InputOTP
      id="pairing-code"
      maxLength={PAIRING_CODE_LENGTH}
      pattern={PAIRING_CODE_PATTERN}
      value={value}
      onChange={(next) => onChange(next.toUpperCase())}
      onComplete={onComplete}
      disabled={isDisabled}
      autoFocus
      // Not an SMS code — it is read off a terminal, and Chrome otherwise
      // refills the field with a previously submitted code on a fresh load.
      autoComplete="off"
      containerClassName="gap-1.5"
      aria-label="Pairing code"
    >
      <InputOTPGroup className="gap-1.5">
        {FIRST_GROUP.map((slot) => (
          <InputOTPSlot key={slot} index={slot} className={SLOT_CLASSNAME} />
        ))}
      </InputOTPGroup>
      <InputOTPSeparator />
      <InputOTPGroup className="gap-1.5">
        {SECOND_GROUP.map((slot) => (
          <InputOTPSlot key={slot} index={slot} className={SLOT_CLASSNAME} />
        ))}
      </InputOTPGroup>
    </InputOTP>
  );
}
