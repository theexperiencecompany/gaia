import type { ReactNode } from "react";

interface HeaderTitleProps {
  icon: ReactNode;
  text: string;
}

export function HeaderTitle({ icon, text }: HeaderTitleProps) {
  return (
    <div className="flex items-center gap-2 pl-0 text-zinc-500">
      {icon}
      <span>{text}</span>
    </div>
  );
}
