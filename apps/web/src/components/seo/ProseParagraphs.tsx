interface ProseParagraphsProps {
  readonly text: string;
  readonly className: string;
}

/** Render marketing-data prose whose paragraphs are separated by blank lines. */
export function ProseParagraphs({ text, className }: ProseParagraphsProps) {
  return (
    <>
      {text.split("\n\n").map((paragraph) => (
        <p
          key={paragraph.slice(0, 40)}
          className={`${className} mb-4 last:mb-0`}
        >
          {paragraph}
        </p>
      ))}
    </>
  );
}
