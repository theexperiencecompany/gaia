import { Loader } from "lucide-react";
import Image from "next/image";

export default function Spinner({
  variant = "logo",
}: { variant?: "simple" | "logo" } = {}) {
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

  return <Loader className="animate-spin text-[24px] text-[#9b9b9b]" />;
}
