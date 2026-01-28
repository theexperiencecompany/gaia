import { Chip } from "@heroui/chip";

export default function LargeHeader({
  chipText,
  headingText,
  subHeadingText,
  chipText2,
  centered = false,
}: {
  chipText?: string;
  chipText2?: string;
  headingText: string;
  subHeadingText?: string;
  centered?: boolean;
}) {
  return (
    <div
      className={`flex max-w-(--breakpoint-xl) flex-col ${centered ? "items-center text-center" : "items-start text-left"}`}
    >
      <div
        className={`flex w-full gap-1 ${centered ? "items-center justify-center" : "items-start justify-start"}`}
      >
        {chipText && (
          <div className="text-primary uppercase mb-2">{chipText}</div>
        )}

        {chipText2 && (
          <Chip variant="flat" color="danger">
            {chipText2}
          </Chip>
        )}
      </div>
      <h2
        className={`relative z-2 my-2 flex gap-4 text-4xl font-medium sm:text-7xl ${centered ? "items-center justify-center" : "items-start justify-start"} font-serif!`}
      >
        {headingText}
      </h2>
      {!!subHeadingText && (
        <div
          className={`max-w-(--breakpoint-md) text-xl text-zinc-400 ${centered ? "text-center" : ""} font-light`}
        >
          {subHeadingText}
        </div>
      )}
    </div>
  );
}
