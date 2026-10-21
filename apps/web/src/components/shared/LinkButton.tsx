import { Button, type ButtonProps } from "@heroui/button";
import Link from "next/link";
import { cn } from "@/lib/utils";

interface LinkButtonProps extends Omit<ButtonProps, "as"> {
  href: string;
  external?: boolean;
}

export function LinkButton({
  href,
  external = false,
  children,
  className,
  ...props
}: LinkButtonProps) {
  if (external) {
    return (
      <Button
        as={"a"}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        variant="light"
        {...props}
        className={cn(
          "text-base h-[30px] w-fit p-2.25 font-medium text-zinc-300",
          className,
        )}
      >
        {children}
      </Button>
    );
  }

  return (
    <Button
      as={Link}
      href={href}
      variant="light"
      radius="sm"
      {...props}
      className={cn(
        "text-base h-[30px] w-fit p-2.25 text-start font-medium text-zinc-300",
        className,
      )}
    >
      {children}
    </Button>
  );
}
