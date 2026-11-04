import { buttonVariants } from "@heroui/react";
import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";

interface LinkButtonProps {
  href: string;
  external?: boolean;
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  size?: "sm" | "md" | "lg";
  variant?:
    | "primary"
    | "secondary"
    | "tertiary"
    | "outline"
    | "ghost"
    | "danger"
    | "danger-soft";
  startContent?: ReactNode;
  "aria-label"?: string;
}

export function LinkButton({
  href,
  external = false,
  children,
  className,
  size = "md",
  variant = "tertiary",
  startContent,
  ...props
}: LinkButtonProps) {
  const classes = cn(buttonVariants({ variant, size }), className);

  const content = (
    <>
      {startContent}
      {children}
    </>
  );

  if (external) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(classes, "text-md font-medium text-zinc-300")}
        style={{ padding: "9px", height: "30px", width: "fit-content" }}
        {...props}
      >
        {content}
      </a>
    );
  }

  return (
    <Link
      href={href}
      className={cn(classes, "text-md text-start font-medium text-zinc-300")}
      style={{ padding: "9px", height: "30px", width: "fit-content" }}
      {...props}
    >
      {content}
    </Link>
  );
}
