# Changelog

## [0.13.0](https://github.com/theexperiencecompany/gaia/compare/api-v0.12.1...api-v0.13.0) (2026-01-29)


### Features

* enhance background task management and fix bot configuration keys to be optional ([#441](https://github.com/theexperiencecompany/gaia/issues/441)) ([5de0c96](https://github.com/theexperiencecompany/gaia/commit/5de0c960740d813e45e46ef3c8074d40ce1fd6d6))
* enhance background task management and improve message persistence handling ([16a28f2](https://github.com/theexperiencecompany/gaia/commit/16a28f22ad9c441817a1fef8c6a535781bc654aa))
* make bot configuration keys optional in ProductionSettings ([6e243ea](https://github.com/theexperiencecompany/gaia/commit/6e243ea534aa26045f81b2e7948c0b2d7d9bece4))

## [0.12.1](https://github.com/theexperiencecompany/gaia/compare/api-v0.12.0...api-v0.12.1) (2026-01-28)


### Features

* add email compose and accordion components, and update mobile auth callback URI. ([cbbd7ee](https://github.com/theexperiencecompany/gaia/commit/cbbd7ee79792df7d8a3239041abc91dccca1bf8f))
* Add new `voice-agent` app to monorepo and introduce shared Python and TypeScript libraries ([#403](https://github.com/theexperiencecompany/gaia/issues/403)) ([3537679](https://github.com/theexperiencecompany/gaia/commit/353767926fc65d591aabca0ee16e744d5b2c11bd))
* Add new `voice-agent` application and introduce shared Python and TypeScript libraries with updated project configuration. ([5f3d854](https://github.com/theexperiencecompany/gaia/commit/5f3d854d1b80e56529f3592c465e26da5ce20451))
* add NotificationProvider and UI updates ([#422](https://github.com/theexperiencecompany/gaia/issues/422)) ([8608485](https://github.com/theexperiencecompany/gaia/commit/8608485f6e4e3372af6919b1c22cd5cb38804642))
* backend set up for register and deregister device token ([04f37d6](https://github.com/theexperiencecompany/gaia/commit/04f37d6bddafb79b608e335a97dbdbfd8a3b1691))
* Implement bearer token authentication for mobile clients, update app configuration ([26d3012](https://github.com/theexperiencecompany/gaia/commit/26d3012473c066b49e21e252c5e322435d1df7d3))
* Implement secure WebSocket authentication via subprotocols and enhance notification error handling for mobile. ([ac16851](https://github.com/theexperiencecompany/gaia/commit/ac168518566a45b1b1db874a8e03a52c1c49ab15))
* init push noti det up ([1d1e0cd](https://github.com/theexperiencecompany/gaia/commit/1d1e0cd66e09a8ee79c4c186ac00e435af67ca3c))
* Introduce chat streaming functionality and integreate Hero UI native ([#410](https://github.com/theexperiencecompany/gaia/issues/410)) ([186e0cb](https://github.com/theexperiencecompany/gaia/commit/186e0cbec1344bb218d783da50cb2a1931f7a305))
* Introduce initial implementations for Discord, Slack, and Telegram bots with supporting API endpoints and shared utilities. ([08f3b55](https://github.com/theexperiencecompany/gaia/commit/08f3b55cbd36771c212a15787f8ab3b882d3d15d))
* **notifications:** add token validation and device limit enforcement ([d8ae2d5](https://github.com/theexperiencecompany/gaia/commit/d8ae2d536b931a87ab9c950ed77c89eec04a74e7))
* **notifications:** enhance push notification handling and add Firebase setup instructions ([0c5c299](https://github.com/theexperiencecompany/gaia/commit/0c5c299572d47cbdecfb38fd370976203985d8ea))
* **notifications:** implement device token management for push notifications ([2137b56](https://github.com/theexperiencecompany/gaia/commit/2137b565525023200cde8c5d89a78525c6349fca))
* **notifications:** implement real-time notifications via WebSocket and add related hooks ([2756256](https://github.com/theexperiencecompany/gaia/commit/27562566d6ed826161decaadd5d146968106f76c))
* prompt optimization for memory ([#436](https://github.com/theexperiencecompany/gaia/issues/436)) ([cfb7dc1](https://github.com/theexperiencecompany/gaia/commit/cfb7dc1399c132ceee3ddb55a2b2a940b1851422))
* prompt optimization for memory ([#436](https://github.com/theexperiencecompany/gaia/issues/436)) ([#440](https://github.com/theexperiencecompany/gaia/issues/440)) ([b33125d](https://github.com/theexperiencecompany/gaia/commit/b33125d3d60402d019d10173d51b8861848cf76a))
* Public Integrations and MCP with Marketplace page ([#430](https://github.com/theexperiencecompany/gaia/issues/430)) ([1ba6055](https://github.com/theexperiencecompany/gaia/commit/1ba6055f8d81c223d33ffc89d0ece1a6d28fa74b))
* push notification for mobile app ([#421](https://github.com/theexperiencecompany/gaia/issues/421)) ([a00820f](https://github.com/theexperiencecompany/gaia/commit/a00820feafa8288488384d1f9ffdcfcaf4431cb7))
* Replace system message deletion with a new node to manage system prompts, preserving memory messages and updating agent graph hooks. ([903eb15](https://github.com/theexperiencecompany/gaia/commit/903eb15db3649d511f79e07045389d896938f258))


### Bug Fixes

* Add docker push to docker:build commands to push images to GHCR ([b4749b8](https://github.com/theexperiencecompany/gaia/commit/b4749b8e8bbd8cf8b3c5cfa36476129d0b0cd760))
* **ci:** Update Docker build commands to include additional image tags for API and voice-agent applications ([878fdbb](https://github.com/theexperiencecompany/gaia/commit/878fdbbec7a387e9046ed48084c4d7298b7090fa))
* **ci:** Update Dockerfiles to use `uv run` for command execution in API and voice-agent applications ([#407](https://github.com/theexperiencecompany/gaia/issues/407)) ([7739606](https://github.com/theexperiencecompany/gaia/commit/7739606cdd390e16b8b3d2889daea7fc42e2ca40))
* Correct Infisical machine identity variable typo, update Dockerfiles to use `uv sync` for dependency installation, and add error handling to voice agent command execution. ([aec25ce](https://github.com/theexperiencecompany/gaia/commit/aec25ce706ed793e1cb3ddd207fbc35529b1194d))
* fixed deps group issues in api ([6a5b2e5](https://github.com/theexperiencecompany/gaia/commit/6a5b2e50840fbcf95d8795ea0e109137f8da9b0b))
* no tool results error ([#416](https://github.com/theexperiencecompany/gaia/issues/416)) ([3006d26](https://github.com/theexperiencecompany/gaia/commit/3006d26275f4b04a0b41d639d4df15fab7b5ef12))
* **notifications:** refactor push notification setup and improve token management ([5f465a3](https://github.com/theexperiencecompany/gaia/commit/5f465a3e251be3db89f2cfd6752153c5413bfb4e))
* streaming issues and minor bugs ([#429](https://github.com/theexperiencecompany/gaia/issues/429)) ([98bb4d7](https://github.com/theexperiencecompany/gaia/commit/98bb4d7ea1ca4f4827093b3062d638a240d689f7))
* temporary removed auto-loading of tools in prod ([2fc4315](https://github.com/theexperiencecompany/gaia/commit/2fc4315f254a882aaf90aba6f9e85ebdbfa27e73))
* Update Dockerfiles to use `uv run` for command execution in API and voice-agent applications ([600a74d](https://github.com/theexperiencecompany/gaia/commit/600a74de0812a528417e41f86cc09ad0c81dea43))
* update mobile redirect URI to use settings configuration ([bc38985](https://github.com/theexperiencecompany/gaia/commit/bc38985b5b5c9df08ac951165bbf79e58094ef88))


### Code Refactoring

* Add voice agent as an app in monorepo with python shared packages ([#404](https://github.com/theexperiencecompany/gaia/issues/404)) ([6ce927e](https://github.com/theexperiencecompany/gaia/commit/6ce927e3343347c398f55b5a494fb72f050637a3))

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


**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/api-v0.11.0...api-v0.12.0

## [0.11.0](https://github.com/theexperiencecompany/gaia/compare/v0.10.1...v0.11.0) (2025-12-19)


### release

* v0.11.0 - New Monorepo setup using NX, Beta Desktop & Mobile app setup, Voice Mode etc ([#378](https://github.com/theexperiencecompany/gaia/issues/378)) ([8e72443](https://github.com/theexperiencecompany/gaia/commit/8e72443a1f56edf8e864cd0258ba26f03c81ddc1))


### Features

* Implement WorkOS mobile SSO and enhance sidebar UI with a new user dropdown menu and updated icons. ([41af75d](https://github.com/theexperiencecompany/gaia/commit/41af75d73bc55099ac3502619758061f2e53b72e))
* introduce OAuth endpoint and settings, update Gemini model, refactor constants and ChromaDB, and enhance workflow and memory management ([4de72d8](https://github.com/theexperiencecompany/gaia/commit/4de72d8608f9fe64a3478e848d35d5fb7f772c1d))
* **mobile:** integrate WorkOS authentication and update app layout ([#382](https://github.com/theexperiencecompany/gaia/issues/382)) ([31dfb2a](https://github.com/theexperiencecompany/gaia/commit/31dfb2ad5286e5b5ed553d299bb54924373e0eb3))
* **mobile:** Setup NativeWindCSS and reusable components ([#380](https://github.com/theexperiencecompany/gaia/issues/380)) ([80d995e](https://github.com/theexperiencecompany/gaia/commit/80d995ef423773e31530fa8fe6178a39db1fde78))
* Setup a monorepo with apps/ directory structure using NX ([#369](https://github.com/theexperiencecompany/gaia/issues/369)) ([230ecb9](https://github.com/theexperiencecompany/gaia/commit/230ecb9611b4fbc16b676010aa831c1a38d0f71e))


### Bug Fixes

* handle extra recipients in gmail_compose_before_hook and add type ignore for plugins ([26edde0](https://github.com/theexperiencecompany/gaia/commit/26edde050b4ea324bb86cf2248bb69ae067dfe12))
* standardize quotes in pnpm-workspace.yaml for consistency and formatting ([fd10238](https://github.com/theexperiencecompany/gaia/commit/fd102387491d1747b55968d1648a0ae1a15f3dd9))


### Miscellaneous Chores

* release 0.5.1 ([a011469](https://github.com/theexperiencecompany/gaia/commit/a011469403974c3e0dc3e19fb39a6c6e8e6e9647))

## 0.10.1 (2025-11-22)

## What's Changed

- fix: Allow sending messages with file uploads and improve tool hashing + batch processing by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/346

**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.10.0...v0.10.1

## 0.10.0 (2025-11-22)

## What's Changed

- refactor(ui): Updated pricing bento cards with new labels and feature sets by @darsh145 in https://github.com/theexperiencecompany/gaia/pull/329
- fix: pricing page issues and payment issues by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/337
- fix: integrate Mem0 v2 API and overhaul memory service & onboarding fixes by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/339
- fix: memory issues related to mem0 by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/340
- feat: enhance subscription settings UI and add new subscription illustration by @darsh145 in https://github.com/theexperiencecompany/gaia/pull/342
- fix: fixed weird message behaviour with indexdb by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/341
- chore: added integration tools and enhanced security for redirect by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/343
- release: security fixes and dexie fixes by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/344

## New Contributors

- @darsh145 made their first contribution in https://github.com/theexperiencecompany/gaia/pull/329

**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.9.1...v0.10.0

## 0.9.1 (2025-11-18)

## What's Changed

- fix: Remove dummy data from explore workflows, workflows ui improvements & minor bug fixes by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/328
- fix: gemini empty ai response by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/330
- feat: enhance ComparisonTable with integration props and improve layout by @SahilSoni27 in https://github.com/theexperiencecompany/gaia/pull/332
- release: v0.9.1 by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/333
- fix: checkpointer posgresql issue by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/335

## New Contributors

- @SahilSoni27 made their first contribution in https://github.com/theexperiencecompany/gaia/pull/332

**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.9.0...v0.9.1

## 0.9.0 (2025-11-17)

## What's Changed

- fix: update integration identifiers for Google services to use lowerc… by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/317
- fix: Bug fixes and production stability improvements by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/321
- fix: Reddit tool improvements by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/322
- release: v0.8.2 by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/325

**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.8.1...v0.9.0

## 0.8.1 (2025-11-14)

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

- add menu accordion state management to UI store ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
- add menu accordion state management to UI store ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
- Better Web Search & Webpage Fetch ([#256](https://github.com/theexperiencecompany/gaia/issues/256)) ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
- enhance SidebarTopButtons with accordion for menu items ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
- enhance SidebarTopButtons with accordion for menu items ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
- improved caching decorators with type-safe model support ([#232](https://github.com/theexperiencecompany/gaia/issues/232)) ([813b631](https://github.com/theexperiencecompany/gaia/commit/813b6311b1a6edeb92c24465c8943a995278ae74))
- Minor onboarding & memory improvements ([#251](https://github.com/theexperiencecompany/gaia/issues/251)) ([9c3da0e](https://github.com/theexperiencecompany/gaia/commit/9c3da0e7bc38df99f8d6cef4e060ded169510682))
- More ai calendar stuff ([#275](https://github.com/theexperiencecompany/gaia/issues/275)) ([46cfc1b](https://github.com/theexperiencecompany/gaia/commit/46cfc1b98d26090cdb2e19dc3de0441157663e6e))
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
- correct metadata key from 'silence' to 'silent' in execute_graph_streaming function ([f54ceb3](https://github.com/theexperiencecompany/gaia/commit/f54ceb3a6f72473f9bdf24bb4e17fa81184ef8bc))
- Don't install uvloop on Windows ([#249](https://github.com/theexperiencecompany/gaia/issues/249)) ([c0f4cb4](https://github.com/theexperiencecompany/gaia/commit/c0f4cb4e86ed3877b6774c126a152bca4a056c19))

### Documentation

- update docs for the new infisical setup ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
- update docs for the new infisical setup ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
