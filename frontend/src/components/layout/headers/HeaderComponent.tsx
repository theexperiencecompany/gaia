import React, { type ReactElement } from "react";

interface IconProps {
  className?: string;
  color?: string;
}

export default function HeaderComponent({
  title = "",
  icon,
  iconClassName = "mr-2 h-6 w-6 text-primary",
  iconColor = "#00bbff",
}: {
  icon?: ReactElement<IconProps>;
  title?: string;
  iconClassName?: string;
  iconColor?: string;
}) {
  return (
    <div className="flex items-center">
      <h1 className="flex items-center gap-2 text-lg font-medium">
        {icon &&
          React.cloneElement(icon, {
            className: iconClassName,
            color: iconColor,
          })}
        {title}
      </h1>
    </div>
  );
}
