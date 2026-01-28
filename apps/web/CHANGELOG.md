# Changelog

## [0.13.0](https://github.com/theexperiencecompany/gaia/compare/web-v0.12.0...web-v0.13.0) (2026-01-28)


### Features

* add chat description in sidebar when new conversation initiated in voice mode ([e4e3849](https://github.com/theexperiencecompany/gaia/commit/e4e384938af57b5e05d4e4235049d0c555f05423))
* add NotificationProvider and UI updates ([#422](https://github.com/theexperiencecompany/gaia/issues/422)) ([8608485](https://github.com/theexperiencecompany/gaia/commit/8608485f6e4e3372af6919b1c22cd5cb38804642))
* Add WaveSpinnerSquare component and wave animation styles ([9768068](https://github.com/theexperiencecompany/gaia/commit/9768068ea700f2044bdc2ec8affac8c4c0750113))
* **notifications:** implement real-time notifications via WebSocket and add related hooks ([2756256](https://github.com/theexperiencecompany/gaia/commit/27562566d6ed826161decaadd5d146968106f76c))
* Public Integrations and MCP with Marketplace page ([#430](https://github.com/theexperiencecompany/gaia/issues/430)) ([1ba6055](https://github.com/theexperiencecompany/gaia/commit/1ba6055f8d81c223d33ffc89d0ece1a6d28fa74b))
* push notification for mobile app ([#421](https://github.com/theexperiencecompany/gaia/issues/421)) ([a00820f](https://github.com/theexperiencecompany/gaia/commit/a00820feafa8288488384d1f9ffdcfcaf4431cb7))
* Retry message and minor landing page improvements ([#427](https://github.com/theexperiencecompany/gaia/issues/427)) ([eb17c6c](https://github.com/theexperiencecompany/gaia/commit/eb17c6ccdd6c55f54622e5e192641bdc153b7934))


### Bug Fixes

* prevent duplicate voice msg by manual sync on endCall ([8f5a9b8](https://github.com/theexperiencecompany/gaia/commit/8f5a9b88dc2452e10fff0be3ffde4467b5e7545d))
* sensitive bar visualizer bug fixed ([9af70b2](https://github.com/theexperiencecompany/gaia/commit/9af70b2333f53be1b767360b34a6461bc4a1eccb))
* streaming issues and minor bugs ([#429](https://github.com/theexperiencecompany/gaia/issues/429)) ([98bb4d7](https://github.com/theexperiencecompany/gaia/commit/98bb4d7ea1ca4f4827093b3062d638a240d689f7))

## 0.12.0 (2025-12-21)

## What's Changed
* feat: Add keyboard shortcuts in navigation, fixed workflow generation from todos by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/379
* chore(release): configure independent versioning for all apps in monorepo by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/385
* feat: Reply to message by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/386
* fix: update Docker Compose production file path in deploy workflow by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/384
* feat: Add support for Unread chats post onboarding and after running workflows by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/388
* refactor: Workflows step generation should be abstract instead of specific tool names. Refactored frontend to use zustand for state management. by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/387
* Revert "feat: Add support for Unread chats" by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/390
* feat: Add support for Unread conversations by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/392
* release: v0.12.0 by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/393
* feat: Add "Tools We Love" page and related components by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/394
* feat: Add "Tools We Love" page and release please configuration changes (#394) by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/396


**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/web-v0.11.0...web-v0.12.0

## [0.11.0](https://github.com/theexperiencecompany/gaia/compare/v0.10.1...v0.11.0) (2025-12-19)


### release

* v0.11.0 - New Monorepo setup using NX, Beta Desktop & Mobile app setup, Voice Mode etc ([#378](https://github.com/theexperiencecompany/gaia/issues/378)) ([8e72443](https://github.com/theexperiencecompany/gaia/commit/8e72443a1f56edf8e864cd0258ba26f03c81ddc1))


### Features

* **mobile:** Setup NativeWindCSS and reusable components ([#380](https://github.com/theexperiencecompany/gaia/issues/380)) ([80d995e](https://github.com/theexperiencecompany/gaia/commit/80d995ef423773e31530fa8fe6178a39db1fde78))
* Setup a monorepo with apps/ directory structure using NX ([#369](https://github.com/theexperiencecompany/gaia/issues/369)) ([230ecb9](https://github.com/theexperiencecompany/gaia/commit/230ecb9611b4fbc16b676010aa831c1a38d0f71e))


### Bug Fixes

* standardize quotes in pnpm-workspace.yaml for consistency and formatting ([fd10238](https://github.com/theexperiencecompany/gaia/commit/fd102387491d1747b55968d1648a0ae1a15f3dd9))


### Miscellaneous Chores

* release 0.5.1 ([a011469](https://github.com/theexperiencecompany/gaia/commit/a011469403974c3e0dc3e19fb39a6c6e8e6e9647))

## 0.10.1 (2025-11-22)

## What's Changed

- fix: Allow sending messages with file uploads and improve tool hashing + batch processing by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/346

**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.10.0...v0.10.1

## 0.10.0 (2025-11-22)

## What's Changed

- fix: Remove dummy data from explore workflows, workflows ui improvements & minor bug fixes by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/328
- fix: gemini empty ai response by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/330
- feat: enhance ComparisonTable with integration props and improve layout by @SahilSoni27 in https://github.com/theexperiencecompany/gaia/pull/332
- release: v0.9.1 by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/333
- fix: checkpointer posgresql issue by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/335
- chore: release master by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/334
- refactor(ui): Updated pricing bento cards with new labels and feature sets by @darsh145 in https://github.com/theexperiencecompany/gaia/pull/329
- fix: pricing page issues and payment issues by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/337
- fix: integrate Mem0 v2 API and overhaul memory service & onboarding fixes by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/339
- fix: memory issues related to mem0 by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/340
- feat: enhance subscription settings UI and add new subscription illustration by @darsh145 in https://github.com/theexperiencecompany/gaia/pull/342
- fix: fixed weird message behaviour with indexdb by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/341
- chore: added integration tools and enhanced security for redirect by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/343
- release: security fixes and dexie fixes by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/344

## New Contributors

- @SahilSoni27 made their first contribution in https://github.com/theexperiencecompany/gaia/pull/332
- @darsh145 made their first contribution in https://github.com/theexperiencecompany/gaia/pull/329

**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.9.0...v0.10.0

## 0.9.0 (2025-11-18)

## What's Changed

- fix: update integration identifiers for Google services to use lowerc… by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/317
- fix: Bug fixes and production stability improvements by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/321
- fix: Reddit tool improvements by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/322
- release: v0.8.2 by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/325
- chore: release master by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/326

**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.8.1...v0.9.0

## 0.8.1 (2025-11-17)

## What's Changed

- chore: add pre-commit tasks, small cleanups, and typing fix by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/300
- ci(workflow): switch to reusable workflow_call for build and deploy by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/302
- ci(workflows): multiple github actions improvements by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/303
- chore: remove uv.lock from git ignore by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/304
- ci(tooling): migrate to prek and fix pre commit issues by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/305
- ci(workflows): always auto-commit ESLint/prek fixes and simplify git push by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/306
- ci(workflows): push prek auto-fixes back to PR branch by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/307
- ci(workflows): cache pnpm for frontend and limit prek auto-commit to PRs by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/308
- ci(workflows): always auto-commit prek fixes by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/309
- ci(workflows): add concurrency to trigger-build job to prevent overlapping branch builds by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/310
- ci(workflows): remove global and trigger-build concurrency controls by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/311
- ci(workflows): upgrade setup-gcloud to v3 and standardize docker/login-action to v3 by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/312
- ci(workflows): pin docker/setup-buildx-action to v3 by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/313
- ci(workflows): discard local changes on GCP VM before pulling latest code by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/314
- ci(workflows): stop containers before pulling and remove --no-deps in deploy job by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/315
- chore: release master by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/301

**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.8.0...v0.8.1

## 0.8.0 (2025-11-14)

## What's Changed

- chore(dx): Setup mise as a task runner for better DX and mprocs to run multiple tasks in a single terminal window by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/288
- feat(ui): added ui to let users connect to intended integration in chat screen by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/290
- fix: fixed token issue in google docs tool by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/291
- chore: Added 2 new Tool calling blogs by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/295
- release: v0.7.1 by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/296
- chore(release-please): remove group-pull-request-title-pattern by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/298

**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.7.0...v0.8.0

## 0.7.0 (2025-11-11)

## What's Changed

- fix: Dexie fetching uses batch syncing & sidebar state updation by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/276
- release: v0.6.1-beta by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/280
- release: v0.6.1-beta by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/282
- chore: release by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/283
- feat: Posthog analytics setup and integrations page by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/284
- feat: added more integrations eg: github, linear, slack etc. by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/271
- release: v0.7.0-beta by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/285
- chore(release): add fallback release-please config and update workflow by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/286

**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.6.0...v0.7.0

## 0.6.1 (2025-11-07)

## What's Changed

- fix: Dexie fetching uses batch syncing & sidebar state updation by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/276
- release: v0.6.1-beta by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/280
- release: v0.6.1-beta by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/282

**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.6.0...v0.6.1

## [0.6.0](https://github.com/theexperiencecompany/gaia/compare/v0.5.1...v0.6.0) (2025-11-07)

### Features

- A better global keyboard command menu ([#258](https://github.com/theexperiencecompany/gaia/issues/258)) ([17bb930](https://github.com/theexperiencecompany/gaia/commit/17bb93076986b4676a9b70b111ddabdc8850a2d3))
- add menu accordion state management to UI store ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
- add menu accordion state management to UI store ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
- Better Web Search & Webpage Fetch ([#256](https://github.com/theexperiencecompany/gaia/issues/256)) ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
- **chat:** Implement Dexie.js Caching ([#240](https://github.com/theexperiencecompany/gaia/issues/240)) ([3b2f30e](https://github.com/theexperiencecompany/gaia/commit/3b2f30e4c09f71a6ae81177966e984cd4c4ef7c6))
- enhance SidebarTopButtons with accordion for menu items ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
- enhance SidebarTopButtons with accordion for menu items ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
- Improve blogs to use Markdown file-based approach ([#269](https://github.com/theexperiencecompany/gaia/issues/269)) ([331cc07](https://github.com/theexperiencecompany/gaia/commit/331cc074f923d9fc1ac1342149a31ac7e6fa3086))
- Minor Landing page improvements + Contact page ([#244](https://github.com/theexperiencecompany/gaia/issues/244)) ([e397158](https://github.com/theexperiencecompany/gaia/commit/e397158cc8e6caf9429fb52b166cca49bdb99a17))
- Minor onboarding & memory improvements ([#251](https://github.com/theexperiencecompany/gaia/issues/251)) ([9c3da0e](https://github.com/theexperiencecompany/gaia/commit/9c3da0e7bc38df99f8d6cef4e060ded169510682))
- More ai calendar stuff ([#275](https://github.com/theexperiencecompany/gaia/issues/275)) ([46cfc1b](https://github.com/theexperiencecompany/gaia/commit/46cfc1b98d26090cdb2e19dc3de0441157663e6e))
- Natural language processing in todo add modal like todoist + minor changes ([#257](https://github.com/theexperiencecompany/gaia/issues/257)) ([07df8f5](https://github.com/theexperiencecompany/gaia/commit/07df8f566c14958fb466f9349a4293eefc5fa047))
- New calendar page & updated tools ([#265](https://github.com/theexperiencecompany/gaia/issues/265)) ([5fe18b3](https://github.com/theexperiencecompany/gaia/commit/5fe18b3dedfdf2f99dd31aa42c6ec5918fac9841))
- Replace web search from deprecated bing API with Tavily & replace manual playwright fetching with firecrawl ([#254](https://github.com/theexperiencecompany/gaia/issues/254)) ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
- Separate Public workflows page with programmatic SEO ([#266](https://github.com/theexperiencecompany/gaia/issues/266)) ([2874591](https://github.com/theexperiencecompany/gaia/commit/287459150787ffd14159177cf8c83f27a507b385))
- speed up follow-up actions by streaming in background ([#242](https://github.com/theexperiencecompany/gaia/issues/242)) ([e94ed6c](https://github.com/theexperiencecompany/gaia/commit/e94ed6cff4194f92f3cdc1263219e2f679fd352e))
- sub-graph system implemented ([#259](https://github.com/theexperiencecompany/gaia/issues/259)) ([f2d362d](https://github.com/theexperiencecompany/gaia/commit/f2d362d086d7f59784f972d27f6075f6ad54a366))
- update dependencies for firecrawl and tavily ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
- update dependencies for firecrawl and tavily ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
- update OAuth and model configurations to use local icon assets ([#239](https://github.com/theexperiencecompany/gaia/issues/239)) ([79bdab9](https://github.com/theexperiencecompany/gaia/commit/79bdab93d38d2d1eef88f9b12930d43f301d4591))

### Bug Fixes

- Calendar Events & Mails not fetching on Chat Page ([#243](https://github.com/theexperiencecompany/gaia/issues/243)) ([5a861fa](https://github.com/theexperiencecompany/gaia/commit/5a861fa3de490a52fba74fe5710c058ff1676834))
