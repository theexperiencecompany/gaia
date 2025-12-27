"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner, type ToasterProps } from "sonner";
import {
  Alert02Icon,
  AlertDiamondIcon,
  CheckmarkCircle01Icon,
  InformationCircleIcon,
} from "../shared/icons";

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme();
  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      expand={true}
      closeButton
      visibleToasts={1}
      icons={{
        success: <CheckmarkCircle01Icon width={20} height={20} />,
        info: <InformationCircleIcon width={20} height={20} />,
        warning: <Alert02Icon width={20} height={20} />,
        error: <AlertDiamondIcon width={20} height={20} />,
      }}
      toastOptions={{
        classNames: {
          toast:
            "rounded-2xl! border-2! backdrop-blur-sm! shadow-black/10! shadow-lg! gap-1.5!",
          loading: "border-2! border-zinc-800! bg-zinc-900!",
          success: "border-2! text-emerald-500!",
          error: "border-2! text-red-400!",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
