import { RedoIcon } from "@icons";
import Image from "next/image";

export default function Spinner({
  variant = "logo",
}: {
  variant?: "simple" | "logo";
} = {}) {
  if (variant === "logo")
    return (
      <div className="animate-spin">
        <Image
          alt="GAIA Logo"
          src={"/images/logos/logo.webp"}
          width={30}
          height={30}
        />
      </div>
    );

  return (
    <div className="animate-spin">
      <RedoIcon className="text-[24px] text-zinc-700" />
    </div>
  );
}
