import { RedoIcon } from "@icons";
import Image from "next/image";

export default function Spinner({
  variant = "logo",
}: {
  variant?: "simple" | "logo";
} = {}) {
  if (variant === "logo")
    return (
      <Image
        alt="GAIA Logo"
        src={"/images/logos/logo.webp"}
        width={30}
        height={30}
        className={`animate-spin`}
      />
    );

  return <RedoIcon className="animate-spin text-[24px] text-zinc-700" />;
}
