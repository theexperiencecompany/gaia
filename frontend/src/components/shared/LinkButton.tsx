import { Button, ButtonProps } from "@heroui/button";
import Link from "next/link";
import { ReactNode } from "react";

interface LinkButtonProps extends Omit<ButtonProps, "href" | "as"> {
  href: string;
  external?: boolean;
  children: ReactNode;
}

export function LinkButton({
  href,
  external = false,
  children,
  ...props
}: LinkButtonProps) {
  if (external) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="no-underline"
      >
        <Button
          variant="light"
          className="text-md h-[30px] w-fit px-[9px] font-medium text-zinc-300"
          {...props}
        >
          {children}
        </Button>
      </a>
    );
  }

  return (
    <Link href={href} className="no-underline">
      <Button
        variant="light"
        radius="sm"
        className="text-md h-[30px] w-fit px-[9px] text-start font-medium text-zinc-300"
        {...props}
      >
        {children}
      </Button>
    </Link>
  );
}
