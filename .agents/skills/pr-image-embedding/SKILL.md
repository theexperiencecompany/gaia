---
name: PR Image Embedding
description: Embed images (benchmark charts, screenshots, diagrams) inline in a GitHub PR or issue description from an agent session, without bloating the code diff. Use when a PR needs visual evidence and you cannot drag-and-drop into the browser.
---

## PR Image Embedding

`gaia` is a **public** repo, so a raw URL to a file on any branch renders inline
in a PR description. Images live on one shared branch, `pr-assets`, never in the
code diff.

### The flow

1. **Generate the image locally**, outside the repo (the session scratchpad), so
   a rejected chart never lands in git history.

2. **Look at it before you ship it.** Read the PNG back with the Read tool.
   Labels overlap, axes collide and text clips; a chart nobody checked is worse
   than none. For app screenshots, also check nothing private is visible: tokens
   in URL bars, emails, real user data.

3. **Commit it to `pr-assets` under a per-PR folder** (`<pr-number>-<topic>/`,
   e.g. `890-anydoc-parsing/`). There is exactly one assets branch; never create
   a branch per PR. Use a throwaway worktree so your own checkout is untouched:

   ```bash
   git fetch origin pr-assets
   git worktree add --detach /tmp/pr-assets origin/pr-assets
   cd /tmp/pr-assets
   mkdir -p <pr-number>-<topic>
   cp -f /path/to/images/*.png <pr-number>-<topic>/
   git add <pr-number>-<topic>/
   git commit -m "Assets for PR #<pr-number> (<topic>), not intended to be merged"
   git push origin HEAD:pr-assets
   cd - && git worktree remove --force /tmp/pr-assets
   ```

4. **Check each URL serves an image** before you embed it:

   ```bash
   curl -s -o /dev/null -w "%{http_code} %{content_type}\n" \
     https://raw.githubusercontent.com/theexperiencecompany/gaia/pr-assets/<pr-number>-<topic>/<file>.png
   ```

   Expect `200 image/png`.

5. **Reference it by raw URL** in the PR body:

   ```markdown
   ![Alt text](https://raw.githubusercontent.com/theexperiencecompany/gaia/pr-assets/<pr-number>-<topic>/<file>.png)
   ```

   Use `![](...)`, never `<img src>`: GitHub sanitizes HTML in some contexts.

6. **Put the numbers in text too**, a table or list beside the charts, so the
   description stands on its own when images don't load (email, terminal, mobile).

### If an image does not render

The URL opens fine but the PR shows alt text: GitHub's image proxy (camo) cached
an earlier failure for that exact URL. Re-upload under a new file name.
