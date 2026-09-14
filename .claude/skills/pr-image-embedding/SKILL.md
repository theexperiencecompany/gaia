---
name: PR Image Embedding
description: Embed images (benchmark charts, screenshots, diagrams) inline in a GitHub PR or issue description from an agent session, end to end and without bloating the code diff. Use whenever a PR needs visual evidence.
---

## PR Image Embedding

GitHub renders inline images through **camo**, its image proxy, and camo fetches
image URLs **unauthenticated**. Anything that needs a session or a token to fetch
will not render — it degrades to alt text that links to the source.

So the only question that matters for any image URL is whether camo can fetch
it. Don't reason about it — check it, in one command:

```bash
/usr/bin/curl -sS -o /dev/null -w "%{http_code}\n" \
  -A "github-camo (b2d0ea9c)" "<raw-url>"        # 200 => camo can fetch it
```

Use `/usr/bin/curl`, not bare `curl`: this environment aliases `curl` to
`curlie`, which silently changes the request method and returns misleading
codes — a plain GET coming back 403/422 is the tell, not evidence about the URL.

### The flow

1. **Generate the image locally.** Write it somewhere outside the repo first
   (the session scratchpad), so a rejected chart never lands in git history.

2. **Look at it before you ship it.** Read the PNG back with the Read tool.
   Labels overlap, axes collide, and text clips constantly — a chart nobody
   verified is worse than no chart, because reviewers trust it.

3. **Commit the images to the single shared assets branch, `pr-assets`, under a
   per-PR folder:**

   There is exactly **one** assets branch — `pr-assets` — and it is never
   duplicated. **Do not create a custom branch per PR.** Every PR's images live
   on `pr-assets`, each under its own folder named for the PR
   (`<pr-number>-<topic>/`, e.g. `890-anydoc-parsing/`). The branch already
   exists and is cut from `master`; update it in place:

   ```bash
   git fetch origin pr-assets
   git checkout -B pr-assets origin/pr-assets
   mkdir -p <pr-number>-<topic>
   cp -f /path/to/charts/*.png <pr-number>-<topic>/
   git add <pr-number>-<topic>/ && git commit -m "Assets for PR #<pr-number> (<topic>)"
   git push -u origin pr-assets
   ```

   Keep them **off the code branch**. Binaries in a code diff are noise a
   reviewer has to scroll past, and they make the PR's real change harder to see.
   A per-PR assets branch is also noise — it forks the history for a handful of
   images, and the single `pr-assets` branch is the one place reviewers (and
   camo) can find them. Say "not intended to be merged" in the commit message.

4. **Reference them by raw URL** in the PR body, always on `pr-assets` under the
   PR's folder:

   ```markdown
   ![Alt text](https://raw.githubusercontent.com/<owner>/<repo>/pr-assets/<pr-number>-<topic>/<file>.png)
   ```

   Use `![](...)`, never `<img src>` — GitHub sanitizes HTML in some contexts,
   and markdown is what the rest of the description uses anyway.

5. **Always include the numbers in text too** — a table or bullet list beside
   the charts. If camo fails, or someone reads the PR in email/on mobile/in a
   terminal, the evidence still survives. This is the cheapest insurance there is.

### If images still don't render

The symptom is specific: **alt text that is clickable and opens the image fine**.
That means the URL is good and camo could not proxy it. Diagnose in this order:

```bash
# 1. Is it actually served as an image? (real binary — see the alias warning above)
/usr/bin/curl -sS -D - -o /dev/null "<url>" | grep -iE "^HTTP|content-type|content-length"

# 2. Does the host block camo's user-agent?
/usr/bin/curl -sS -o /dev/null -w "%{http_code}\n" -A "github-camo (b2d0ea9c)" "<url>"
```

Known blockers, in rough order of likelihood:

| Cause | Fix |
|---|---|
| A bare `curl` that is really `curlie` reporting a bogus 403/422 | Re-check with `/usr/bin/curl` before concluding anything |
| A GitHub **UI** URL (`github.com/.../blob/...`) instead of `raw.githubusercontent.com` | Use the raw URL |
| The URL needs auth to fetch (camo has no session) | Host it somewhere camo can reach; last resort only if nothing can |
| Missing `Content-Length` header on the host | Not fixable from our side — change hosts |
| Host blocks or challenges camo's UA (Cloudflare bot protection) | Change hosts |
| Camo cached an earlier failure for that exact URL | Re-upload under a new URL |

### Fix it yourself — the moves before you consider involving the user

Every row in that table except one is an agent fix. Work them:

1. **Re-check with `/usr/bin/curl`.** Most "it's broken" readings are the alias.
2. **Correct the URL shape** — `raw.githubusercontent.com/<owner>/<repo>/<branch>/<path>`,
   never a `blob` UI link.
3. **Re-upload under a new path** (`<pr>-<topic>-v2/<file>.png`) and point the
   markdown at it. Camo caches per-URL, including cached failures, so a fresh
   path is a genuine fix, not a superstition.
4. **Confirm the asset is really on the branch** — `gh api
   repos/<owner>/<repo>/contents/<path>?ref=pr-assets` — before blaming camo.
5. **Try a different host** the user already trusts (below), and verify the
   returned URL the same way.

Only when all of those have actually been tried and failed is this a human's
problem. Handing the user files to drag in is not a fallback plan, it is
admitting defeat — it costs them time on something automatable and it usually
means a check above was skipped. Do not offer it as a first-class option, and
never present it as "the guaranteed way".

### Genuine last resort

If — and only if — the moves above are exhausted: GitHub's own attachment
upload always renders, because GitHub serves it to the authenticated viewer
(`https://github.com/user-attachments/assets/<uuid>`). There is no API for it;
it exists only in the browser. Hand the files over (`SendUserFile`), say
precisely which checks you ran and what each returned, and ask for the drag-in.
The explanation is mandatory — otherwise you are asking the user to do your job
without evidence that it needed doing.

### Third-party image hosts

Workable, but treat with care and never as the default:

- It **publishes the content publicly** — it may be cached or indexed even
  after deletion. Never upload anything containing internal code, hostnames,
  credentials, customer data, or unreleased product detail. Benchmark charts and
  generic diagrams are fine; a screenshot of the app with real data is not.
- Confirm the host is one the user actually trusts before sending anything.
- Verify what came back: fetch the returned URL and **look at the image**.
  Hosts recompress (a changed byte count/checksum is normal and not evidence of
  tampering — check the pixels, not the hash).
- Many such hosts still won't render inline for the reasons in the table above —
  verify with the camo check rather than assuming either way.

### Rules of thumb

- You cannot see the rendered PR — but you can prove the precondition. Fetch the
  raw URL as camo (above) and say what you verified: "the asset returns 200 as
  `image/png` to camo's user-agent, so it renders." Don't hedge with "I can't
  check" when a check exists, and don't claim the rendered page looks right.
- Never let the PR sit with broken image markup. Either fix it or strip the tags
  and leave the numbers in text.
- The charts are a convenience; the text is the record. Write the description so
  it stands on its own with every image stripped out.
