import {
  type ComponentRenderProps,
  defineComponent,
} from "@openuidev/react-lang";
import Link from "next/link";
import { useContext } from "react";
import type { z } from "zod";
import { GroundedText } from "../GroundedText";
import { type ArtifactDensity, ArtifactDensityContext } from "../renderContext";
import {
  artifactSchema,
  calloutSchema,
  type calloutTone,
  columnsSchema,
  describeArtifactComponent,
  paragraphSchema,
  quoteSchema,
  sectionSchema,
  sourcesSchema,
  takeawaysSchema,
  todoSchema,
} from "../specs";

// Views stay file-private: this module's surface is the defs (react-refresh/only-export-components).

const TONE_SURFACE: Record<z.infer<typeof calloutTone>, string> = {
  note: "bg-accent/10",
  good: "bg-success/10",
  warn: "bg-warning/10",
  risk: "bg-danger/10",
};
const TONE_TEXT: Record<z.infer<typeof calloutTone>, string> = {
  note: "text-accent",
  good: "text-success",
  warn: "text-warning",
  risk: "text-danger",
};

const ROOT_CLASSES: Record<
  ArtifactDensity,
  { article: string; header: string; title: string; subtitle: string }
> = {
  page: {
    article: "px-5 pt-12 pb-10",
    header: "mb-12",
    title: "text-[clamp(1.875rem,1.45rem+1.75vw,2.75rem)]",
    subtitle: "mt-4 text-xl",
  },
  card: {
    article: "p-5",
    header: "mb-6",
    title: "text-2xl",
    subtitle: "mt-2 text-base",
  },
};

function ArtifactRoot({
  props,
  renderNode,
}: ComponentRenderProps<z.infer<typeof artifactSchema>>) {
  const density = useContext(ArtifactDensityContext);
  const classes = ROOT_CLASSES[density];
  return (
    <article
      className={`mx-auto w-full max-w-5xl overflow-x-clip ${classes.article}`}
    >
      <header className={classes.header}>
        <h1
          className={`m-0 font-serif leading-tight font-bold tracking-tight text-foreground ${classes.title}`}
        >
          <GroundedText text={props.title} />
        </h1>
        <p className={`leading-relaxed text-foreground/80 ${classes.subtitle}`}>
          <GroundedText text={props.subtitle} />
        </p>
        {props.details?.length ? (
          <ul className="mt-5 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted">
            {props.details.map((detail) => (
              <li key={detail}>
                <GroundedText text={detail} />
              </li>
            ))}
          </ul>
        ) : null}
      </header>
      <div className="flex flex-col gap-6">{renderNode(props.children)}</div>
      {density === "page" ? (
        <footer className="mt-16 pt-5 text-sm text-muted">
          Prepared by GAIA
        </footer>
      ) : null}
    </article>
  );
}

export const artifactDef = defineComponent({
  name: "Artifact",
  description: describeArtifactComponent("Artifact"),
  props: artifactSchema,
  component: ArtifactRoot,
});

export const sectionDef = defineComponent({
  name: "Section",
  description: describeArtifactComponent("Section"),
  props: sectionSchema,
  component: ({ props, renderNode }) => (
    <section className="mt-10 flex flex-col gap-5">
      <header>
        <h2 className="text-[1.75rem] font-semibold tracking-tight text-foreground">
          <GroundedText text={props.title} />
        </h2>
        {props.summary ? (
          <p className="mt-1 text-muted">
            <GroundedText text={props.summary} />
          </p>
        ) : null}
      </header>
      {renderNode(props.children)}
    </section>
  ),
});

export const columnsDef = defineComponent({
  name: "Columns",
  description: describeArtifactComponent("Columns"),
  props: columnsSchema,
  component: ({ props, renderNode }) => (
    <div className="grid min-w-0 gap-4 md:auto-cols-fr md:grid-flow-col">
      {renderNode(props.children)}
    </div>
  ),
});

export const paragraphDef = defineComponent({
  name: "Paragraph",
  description: describeArtifactComponent("Paragraph"),
  props: paragraphSchema,
  component: ({ props }) => (
    <p className="text-[1.0625rem] leading-relaxed text-foreground/90">
      <GroundedText text={props.text} />
    </p>
  ),
});

export const takeawaysDef = defineComponent({
  name: "Takeaways",
  description: describeArtifactComponent("Takeaways"),
  props: takeawaysSchema,
  component: ({ props }) => (
    <div className="flex flex-col gap-2 rounded-2xl bg-default p-6">
      <p className="text-sm font-semibold text-muted">In short</p>
      <ul className="list-disc space-y-2 pl-5 marker:text-accent">
        {props.items.map((item) => (
          <li key={item}>
            <GroundedText text={item} />
          </li>
        ))}
      </ul>
    </div>
  ),
});

export const calloutDef = defineComponent({
  name: "Callout",
  description: describeArtifactComponent("Callout"),
  props: calloutSchema,
  component: ({ props }) => (
    <div className={`rounded-2xl p-5 ${TONE_SURFACE[props.tone]}`}>
      <p>
        <strong className={`font-semibold ${TONE_TEXT[props.tone]}`}>
          <GroundedText text={props.title} />
        </strong>{" "}
        <GroundedText text={props.text} />
      </p>
    </div>
  ),
});

export const quoteDef = defineComponent({
  name: "Quote",
  description: describeArtifactComponent("Quote"),
  props: quoteSchema,
  component: ({ props }) => (
    <figure className="my-4 pl-6">
      <blockquote className="text-xl font-medium tracking-tight text-foreground italic">
        <GroundedText text={props.text} />
      </blockquote>
      <figcaption className="mt-2 text-sm text-muted">
        {props.attribution}
      </figcaption>
    </figure>
  ),
});

export const todoDef = defineComponent({
  name: "Todo",
  description: describeArtifactComponent("Todo"),
  props: todoSchema,
  component: ({ props }) => (
    <ul className="list-none p-0">
      {props.items.map(([verb, text, side]) => (
        <li
          key={`${verb} ${text}`}
          className="flex flex-col gap-1 border-b border-separator py-3 last:border-0 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4"
        >
          <span>
            <strong className="font-semibold text-foreground">{verb}</strong>{" "}
            <GroundedText text={text} />
          </span>
          {side ? (
            <span className="text-sm whitespace-nowrap text-muted">{side}</span>
          ) : null}
        </li>
      ))}
    </ul>
  ),
});

export const sourcesDef = defineComponent({
  name: "Sources",
  description: describeArtifactComponent("Sources"),
  props: sourcesSchema,
  component: ({ props }) => (
    <ol className="list-decimal pl-6 text-sm text-muted">
      {props.items.map(([title, publisher, url]) => (
        <li key={`${title} ${publisher}`}>
          {url ? (
            <Link
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-accent underline"
            >
              {title}
            </Link>
          ) : (
            title
          )}
          . {publisher}
        </li>
      ))}
    </ol>
  ),
});
