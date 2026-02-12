import Image from "next/image";
import type { ReactNode } from "react";

interface FeatureCardProps {
  imageSrc?: string;
  title: string;
  description?: string;
  imageAlt?: string;
  small?: boolean;
  reverse?: boolean;
  icon?: ReactNode;
  className?: string;
  imageClassName?: string;
  children?: ReactNode;
  childrenBeforeHeading?: ReactNode;
}

export function FeatureCard({
  imageSrc,
  title,
  description,
  imageAlt = title,
  small = false,
  reverse = false,
  icon,
  className = "",
  imageClassName = "object-contain",
  children,
  childrenBeforeHeading = false,
}: FeatureCardProps) {
  return (
    <div
      className={`${className} flex h-full w-full ${reverse ? "flex-col-reverse" : "flex-col"} bg-zinc-900 ${small ? "rounded-2xl p-4" : "rounded-3xl p-6"}`}
    >
      {imageSrc && (
        <div
          className={`relative w-full flex-1 overflow-hidden rounded-2xl ${reverse ? "mt-3" : "mb-3"}`}
        >
          <Image
            fill
            src={imageSrc}
            sizes="(max-width: 768px) 100vw, 50vw"
            loading="lazy"
            className={`${imageClassName} `}
            alt={imageAlt}
          />
        </div>
      )}
      <div className="flex flex-col gap-1">
        {icon && (
          <div className="mb-2">
            <div className={`${small ? "text-2xl" : "text-4xl"} text-white`}>
              {icon}
            </div>
          </div>
        )}
        {childrenBeforeHeading && <div>{childrenBeforeHeading}</div>}
        <div
          className={`font-medium text-white ${small ? "text-xl" : "text-3xl"}`}
        >
          {title}
        </div>
        {description && (
          <div className={`text-zinc-400 ${small ? "text-sm" : "text-medium"}`}>
            {description}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
