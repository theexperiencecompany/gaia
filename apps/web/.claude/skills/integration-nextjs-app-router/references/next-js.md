> AI agents: this is one page from PostHog's docs. Full index of Markdown docs for LLMs: https://posthog.com/llms.txt

# Next.js - Docs

Copy page

# Next.js - Docs

PostHog makes it easy to get data about traffic and usage of your [Next.js](https://nextjs.org/) app. Integrating PostHog into your site enables analytics about user behavior, custom events capture, session recordings, feature flags, and more.

This guide walks you through integrating PostHog into your Next.js app using the [React](/docs/libraries/react.md) and the [Node.js](/docs/libraries/node.md) SDKs.

> You can see a working example of this integration in our [Next.js demo app](https://github.com/PostHog/posthog-js/tree/main/playground/nextjs).

Next.js has both client and server-side rendering, as well as pages and app routers. We'll cover all of these options in this guide.

> **Try `@posthog/next` (pre-release):** A simplified Next.js integration with synchronized client/server identity, server-side flag bootstrapping, and a built-in API proxy. [Read the setup guide →](/docs/libraries/next-js/posthog-next.md)

## Prerequisites

To follow this guide along, you need:

1.  A PostHog instance (either [Cloud](https://app.posthog.com/signup) or [self-hosted](/docs/self-host.md))
2.  A Next.js application

## Beta: integration via LLM

Install PostHog for Next.js in seconds with our wizard by running this prompt with [LLM coding agents](/blog/envoy-wizard-llm-agent.md) like Cursor and Bolt, or by running it in your terminal.

`npx @posthog/wizard`

[Learn more](/wizard.md)

Or, to integrate manually, continue with the rest of this guide.

## Client-side setup

Install `posthog-js` using your package manager:

PostHog AI

### npm

```bash
npm install --save posthog-js
```

### Yarn

```bash
yarn add posthog-js
```

### pnpm

```bash
pnpm add posthog-js
```

### Bun

```bash
bun add posthog-js
```

> **If your site sets a Content-Security-Policy**, it needs to allow PostHog. This applies to the snippet and to package installs alike: the SDK lazy-loads extra bundles (session replay, surveys) from PostHog's CDN, and sends events to the ingestion host. PostHog serves from subdomains of `posthog.com` that change over time, so allow the wildcard:
>
> PostHog AI
>
> ```
> script-src 'self' https://*.posthog.com;
> connect-src 'self' https://*.posthog.com;
> worker-src 'self' blob: data:;
> ```
>
> `script-src` covers the snippet and the lazy-loaded bundles, `connect-src` covers event ingestion and feature flags, and `worker-src` covers session replay. The [toolbar needs a few more](/docs/advanced/content-security-policy.md), or use a [reverse proxy](/docs/advanced/proxy.md) so everything is first-party. Failing to do so causes silent failures where `capture` and `identify` calls never send, so the integration looks complete while zero events arrive. Remember `connect-src` falls back to `default-src`, so `default-src 'self'` blocks event delivery even when the script itself is bundled.

Add your environment variables to your `.env.local` file and to your hosting provider (e.g. Vercel, Netlify, AWS). You can find your project token in your [project settings](https://app.posthog.com/project/settings).

.env.local

PostHog AI

```shell
NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN=<ph_project_token>
NEXT_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com
```

These values need to start with `NEXT_PUBLIC_` to be accessible on the client-side.

## Integration

Next.js provides the [`instrumentation-client.ts|js`](https://nextjs.org/docs/app/api-reference/file-conventions/instrumentation-client) file for client-side setup. Add it to the root of your Next.js app (for both app and pages router) and initialize PostHog in it like this:

PostHog AI

### instrumentation-client.js

```javascript
import posthog from 'posthog-js'
posthog.init(process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN, {
  api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
  defaults: '2026-05-30'
});
```

### instrumentation-client.ts

```typescript
import posthog from 'posthog-js'
posthog.init(process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN!, {
  api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
  defaults: '2026-05-30'
});
```

Bootstrapping with `instrumentation-client`

When using `instrumentation-client`, the values you pass to `posthog.init` remain fixed for the entire session. This means bootstrapping only works if you evaluate flags **before your app renders** (for example, on the server).

If you need flag values after the app has rendered, you’ll want to:

-   Evaluate the flag on the server and pass the value into your app, or
-   Evaluate the flag in an earlier page/state, then store and re-use it when needed.

Both approaches avoid flicker and give you the same outcome as bootstrapping, as long as you use the same `distinct_id` across client and server.

See the [bootstrapping guide](/docs/feature-flags/bootstrapping.md) for more information.

## Identifying users

> **Identifying users is required.** Call `posthog.identify('your-user-id')` after login to link events to a known user. This is what connects frontend event captures, [session replays](/docs/session-replay.md), [LLM traces](/docs/ai-engineering.md), and [error tracking](/docs/error-tracking.md) to the same person — and lets backend events link back too.
>
> Use a stable ID from your auth system when possible, not an email or display name. Send those as person properties instead. If your app has no other stable key, email works as a fallback if they are unique. Never a shared literal like `"anonymous"` or `"user"`, which pools many people onto one person and corrupts their data. When no ID is available at all, skip the identify and retain the anonymous distinct ID that's automatically assigned.
>
> Call `posthog.reset()` on logout, so the next person to use the browser doesn't inherit the last one's identity.
>
> See our guide on [identifying users](/docs/getting-started/identify-users.md) for how to set this up.

### Linking client and server events

Next.js apps usually capture on both sides. To keep them on the same person, use the same distinct ID in both, and let the browser tell your server which one that is.

If your app calls your own backend, `tracing_headers` adds `X-POSTHOG-DISTINCT-ID` and `X-POSTHOG-SESSION-ID` to matching `fetch` and `XMLHttpRequest` requests. This lets server-side SDKs link backend events, errors, and LLM traces back to frontend sessions and replays. Use hostnames only, without protocols or paths.

JavaScript

PostHog AI

```javascript
posthog.init('<ph_project_token>', {
  api_host: 'https://us.i.posthog.com',
  // Optional: send PostHog session/user context to your backend
  tracing_headers: ['api.example.com'],
})
```

This works in local development too, but match on the hostname alone: use `'localhost'`, not `'localhost:3000'`. Ports are never part of a hostname, so a value with one in it never matches anything. `localhost` and `127.0.0.1` are also different hostnames — use whichever your app actually calls.

Tracing headers help you attribute events across front and backend consistently. When this isn't available, use your server-side stable IDs to deduce the matching `distinctId`, and pass it in when capturing the event.

Set up a reverse proxy (recommended)

We recommend [setting up a reverse proxy](/docs/advanced/proxy.md), so that events are less likely to be intercepted by tracking blockers.

We have our [own managed reverse proxy service](/docs/advanced/proxy/managed-reverse-proxy.md), which is free for all PostHog Cloud users, routes through our infrastructure, and makes setting up your proxy easy.

If you don't want to use our managed service then there are several other options for creating a reverse proxy, including using [Cloudflare](/docs/advanced/proxy/cloudflare.md), [AWS Cloudfront](/docs/advanced/proxy/cloudfront.md), and [Vercel](/docs/advanced/proxy/vercel.md).

Grouping products in one project (recommended)

If you have multiple customer-facing products (e.g. a marketing website + mobile app + web app), it's best to install PostHog on them all and [group them in one project](/docs/settings/projects.md).

This makes it possible to track users across their entire journey (e.g. from visiting your marketing website to signing up for your product), or how they use your product across multiple platforms.

Add IPs to Firewall/WAF allowlists (recommended)

For certain features like [heatmaps](/docs/toolbar/heatmaps.md), your Web Application Firewall (WAF) may be blocking PostHog's requests to your site. Add these IP addresses to your WAF allowlist or rules to let PostHog access your site.

**EU**: `3.75.65.221`, `18.197.246.42`, `3.120.223.253`

**US**: `44.205.89.55`, `52.4.194.122`, `44.208.188.173`

These are public, stable IPs used by PostHog services (e.g., Celery tasks for snapshots).

## Accessing PostHog

Once initialized in `instrumentation-client.js|ts`, import `posthog` from `posthog-js` anywhere and call the methods you need on the `posthog` object.

JavaScript

PostHog AI

```javascript
"use client";
import posthog from "posthog-js";
export default function Home() {
  return (
    <div>
      <button onClick={() => posthog.capture("test_event")}>Click me for an event</button>
    </div>
  );
}
```

### Using React hooks

The [React feature flag hooks](/docs/libraries/react.md#feature-flags) work automatically when PostHog is initialized via `instrumentation-client.ts`. The hooks use the initialized posthog-js singleton:

JavaScript

PostHog AI

```javascript
"use client";
import { useFeatureFlagEnabled } from "@posthog/react";
export default function FeatureComponent() {
  const showNewFeature = useFeatureFlagEnabled("new-feature");
  return showNewFeature ? <NewFeature /> : <OldFeature />;
}
```

### Usage

See the [React SDK docs](/docs/libraries/react.md) for examples of how to use:

-   [`posthog-js` functions like custom event capture, user identification, and more.](/docs/libraries/react.md#using-posthog-js-functions)
-   [Feature flags including variants and payloads.](/docs/libraries/react.md#feature-flags)

You can also read [the full `posthog-js` documentation](/docs/libraries/js/usage.md) for all the usable functions.

## Server-side analytics

Next.js enables you to both server-side render pages and add server-side functionality. To integrate PostHog into your Next.js app on the server-side, you can use the [Node SDK](/docs/libraries/node.md).

First, install the `posthog-node` library:

PostHog AI

### npm

```bash
npm install posthog-node --save
```

### Yarn

```bash
yarn add posthog-node
```

### pnpm

```bash
pnpm add posthog-node
```

### Bun

```bash
bun add posthog-node
```

### Router-specific instructions

## App router

For the app router, we can initialize the `posthog-node` SDK once with a `PostHogClient` function, and import it into files.

This enables us to send events and fetch data from PostHog on the server – without making client-side requests.

JavaScript

PostHog AI

```javascript
// app/posthog.js
import { PostHog } from 'posthog-node'
export default function PostHogClient() {
  const posthogClient = new PostHog(process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN, {
    host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
    flushAt: 1,
    flushInterval: 0
  })
  return posthogClient
}
```

> **Note:** Because server-side functions in Next.js can be short-lived, we set `flushAt` to `1` and `flushInterval` to `0`.
>
> -   `flushAt` sets how many capture calls we should flush the queue (in one batch).
> -   `flushInterval` sets how many milliseconds we should wait before flushing the queue. Setting them to the lowest number ensures events are sent immediately and not batched. We also need to call `await posthog.shutdown()` once done.

To use this client, we import it into our pages and call it with the `PostHogClient` function:

JavaScript

PostHog AI

```javascript
import Link from 'next/link'
import PostHogClient from '../posthog'
export default async function About() {
  const posthog = PostHogClient()
  const flags = await posthog.getAllFlags(
    'user_distinct_id' // replace with a user's distinct ID
  );
  await posthog.shutdown()
  return (
    <main>
      <h1>About</h1>
      <Link href="/">Go home</Link>
      { flags['main-cta'] &&
        <Link href="http://posthog.com/">Go to PostHog</Link>
      }
    </main>
  )
}
```

## Pages router

For the pages router, we can use the `getServerSideProps` function to access PostHog on the server-side, send events, evaluate feature flags, and more.

This looks like this:

JavaScript

PostHog AI

```javascript
// pages/posts/[id].js
import { useContext, useEffect, useState } from 'react'
import { getServerSession } from "next-auth/next"
import { authOptions } from '@/lib/auth'
import { PostHog } from 'posthog-node'
export default function Post({ post, flags }) {
  const [ctaState, setCtaState] = useState()
  useEffect(() => {
    if (flags) {
      setCtaState(flags['blog-cta'])
    }
  })
  return (
    <div>
      <h1>{post.title}</h1>
      <p>By: {post.author}</p>
      <p>{post.content}</p>
      {ctaState &&
        <p><a href="/">Go to PostHog</a></p>
      }
      <button onClick={likePost}>Like</button>
    </div>
  )
}
export async function getServerSideProps(ctx) {
  // Pass authOptions, or your session callbacks don't run.
  const session = await getServerSession(ctx.req, ctx.res, authOptions)
  let flags = null
  if (session) {
    const client = new PostHog(
      process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN,
      {
        host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
      }
    )
    // A stable ID from your auth system, not an email. See the note below.
    const distinctId = session.user.id
    flags = await client.getAllFlags(distinctId);
    client.capture({
      distinctId,
      event: 'loaded blog article',
      properties: {
        $current_url: ctx.req.url,
      },
    });
    await client.shutdown()
  }
  const { posts } = await import('../../blog.json')
  const post = posts.find((post) => post.id.toString() === ctx.params.id)
  return {
    props: {
      post,
      flags
    },
  }
}
```

> **Note**: next-auth doesn't put a user ID on the session by default. Its session is `{ name, email, image }`, so `session.user.id` is `undefined` until you add it yourself with a session callback in your `authOptions`:
>
> JavaScript
>
> PostHog AI
>
> ```javascript
> // lib/auth.js
> export const authOptions = {
>   callbacks: {
>     session({ session, token, user }) {
>       // JWT sessions (the default) carry the user ID in token.sub.
>       // Database sessions get it from user.id instead.
>       session.user.id = token?.sub ?? user.id
>       return session
>     },
>   },
> }
> ```
>
> Capturing with an `undefined` distinct ID creates events that belong to nobody, so check that the ID arrives before relying on it.

> **Note**: Make sure to *always* call `await client.shutdown()` after sending events from the server-side. PostHog queues events into larger batches, and this call forces all batched events to be flushed immediately.

### Server-side configuration

Next.js overrides the default `fetch` behavior on the server to introduce their own cache. PostHog ignores that cache by default, as this is Next.js's default behavior for any fetch call.

You can override that configuration when initializing PostHog, but make sure you understand the pros/cons of using Next.js's cache and that you might get cached results rather than the actual result our server would return. This is important for feature flags, for example.

TSX

PostHog AI

```jsx
posthog.init(process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN, {
  // ... your configuration
  fetch_options: {
    cache: 'force-cache', // Use Next.js cache
    next_options: {       // Passed to the `next` option for `fetch`
      revalidate: 60,     // Cache for 60 seconds
      tags: ['posthog'],  // Can be used with Next.js `revalidateTag` function
    },
  }
})
```

## Configuring a reverse proxy to PostHog

To improve the reliability of client-side tracking and make requests less likely to be intercepted by tracking blockers, you can setup a reverse proxy in Next.js. Read more about deploying a reverse proxy using [Next.js rewrites](/docs/advanced/proxy/nextjs.md), [Next.js middleware](/docs/advanced/proxy/nextjs-middleware.md), and [Vercel rewrites](/docs/advanced/proxy/vercel.md).

## Further reading

-   [How to set up Next.js analytics, feature flags, and more](/tutorials/nextjs-analytics.md)
-   [How to set up Next.js pages router analytics, feature flags, and more](/tutorials/nextjs-pages-analytics.md)
-   [How to set up Next.js A/B tests](/tutorials/nextjs-ab-tests.md)

### Was this page useful?

HelpfulCould be better