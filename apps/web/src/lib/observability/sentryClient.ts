/**
 * The Sentry functions the browser uses, as named imports so the bundler drops
 * the rest; a namespace import() kept replay, feedback and their peers in the chunk.
 */
export {
  captureRouterTransitionStart,
  getClient,
  init,
  lazyLoadIntegration,
} from "@sentry/nextjs";
