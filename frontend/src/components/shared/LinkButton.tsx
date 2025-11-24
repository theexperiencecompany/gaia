import { Button, type ButtonProps } from "@heroui/button";
import Link from "next/link";

interface LinkButtonProps extends ButtonProps {
  href: string;
  external?: boolean;
}

export function LinkButton({
  href,
  external = false,
  children,
  ...props
}: LinkButtonProps) {
  if (external) {
    return (
      <Button
        as="a"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        variant="light"
        className="text-md font-medium text-zinc-300"
        style={{ padding: "9px", height: "30px", width: "fit-content" }}
        {...props}
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
      style={{ padding: "9px", height: "30px", width: "fit-content" }}
      className="text-md text-start font-medium text-zinc-300"
      {...props}
    >
      {children}
    </Button>
  );
}
