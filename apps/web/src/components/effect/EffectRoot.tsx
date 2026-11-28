"use client";

import type { Component } from "@effect/ui";
import { BrowserHost } from "@effect/ui/html";
import { ApiLive } from "@heygaia/effect-ui";
import { Effect, Fiber, Layer } from "effect";
import { useEffect, useRef } from "react";

/**
 * Mounts one Effect UI root per Next route. One root, not one per widget:
 * each root owns its query cache, so multiple mounts would duplicate fetches.
 *
 * Next keeps routing, auth, locale, and metadata during the migration. This
 * bridge is the only React code a ported route needs.
 */
export function EffectRoot<C extends Component.Any>({
  component,
  props,
  apiBaseUrl,
}: {
  readonly component: C;
  readonly props: Component.Props<C>;
  readonly apiBaseUrl: string;
}) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!host.current) return;

    // BrowserHost.mount is generic over the component's Schema. The bridge
    // accepts the erased type because Next cannot carry that inference across
    // the package boundary; the page still checks its props at the call site.
    const main = BrowserHost.mount(
      component as unknown as Parameters<typeof BrowserHost.mount>[0],
      props as never,
      host.current,
    ).pipe(Layer.provide(ApiLive(apiBaseUrl))) as Layer.Layer<
      never,
      never,
      never
    >;

    const fiber = Effect.runFork(Layer.launch(main));

    return () => {
      Effect.runFork(Fiber.interrupt(fiber));
    };
  }, [apiBaseUrl, component, props]);

  return <div ref={host} data-effect-ui-root />;
}
