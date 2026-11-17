import { Link } from "@heroui/react";
import { Alert01Icon } from "@icons";
import { toneVariants } from "@/components/shared/tone";

/** Shown when this instance only accepts sign-ups through an invite link. */
export function RegistrationClosedNotice() {
  return (
    <div className="flex flex-col items-center gap-4" role="alert">
      <div className="flex items-center gap-2 rounded-xl bg-amber-400/10 px-3 py-2 text-sm text-amber-400">
        <Alert01Icon height={17} className="shrink-0" />
        Sign-ups here need an invite link. Ask the person who runs this GAIA.
      </div>
      <Link
        href="/login"
        className={toneVariants({
          tone: "accent",
          className: "text-sm hover:underline",
        })}
      >
        Sign in instead
      </Link>
    </div>
  );
}
