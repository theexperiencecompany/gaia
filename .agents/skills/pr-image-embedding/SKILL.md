---
name: PR Image Embedding
description: Embed images (benchmark charts, screenshots, diagrams) inline in a GitHub PR or issue description from an agent session, without bloating the code diff. Use when a PR needs visual evidence and you cannot drag-and-drop into the browser.
---

## PR Image Embedding

`gaia` is a **private** repo. That single fact drives every rule below, because
GitHub renders inline images through **camo**, its image proxy, and camo fetches
image URLs **unauthenticated**. Anything that needs a session or a token to fetch
will not render — it degrades to alt text that links to the source.

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
# 1. Is it actually served as an image?
curl -sS -D - -o /dev/null "<url>" | grep -iE "^HTTP|content-type|content-length"

# 2. Does the host block camo's user-agent?
curl -sS -o /dev/null -w "%{http_code}\n" -A "github-camo (b2d0ea9c)" "<url>"
```

Known blockers, in rough order of likelihood:

| Cause | Fix |
|---|---|
| Private-repo URL needing auth (`raw.githubusercontent.com` on a private repo, or a GitHub UI URL) | Use GitHub's own attachment upload (below) |
| Missing `Content-Length` header on the host | Not fixable from our side — change hosts |
| Host blocks or challenges camo's UA (Cloudflare bot protection) | Change hosts |
| Camo cached an earlier failure for that exact URL | Re-upload under a new URL |

### The guaranteed fallback

GitHub's own attachment upload always renders, in private repos included,
because GitHub serves it to the authenticated viewer. It produces a
`https://github.com/user-attachments/assets/<uuid>` URL.

**There is no API for it** — it only exists in the browser. So an agent cannot
do this step. Hand the files to the user (`SendUserFile`) and have them drag the
images into the PR description box. Ten seconds of their time, guaranteed result.

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
- Many such hosts still won't render inline for the reasons in the table above,
  so you can do everything right here and still end up back at the fallback.

### Rules of thumb

- Never claim images render until the user confirms it — you cannot see the
  rendered PR, and a private repo means you cannot fetch it to check.
- Never let the PR sit with broken image markup. Either fix it or strip the tags
  and leave the numbers in text.
- The charts are a convenience; the text is the record. Write the description so
  it stands on its own with every image stripped out.
