# Changelog

## 0.7.0 (2025-11-11)

## What's Changed
* fix: Dexie fetching uses batch syncing & sidebar state updation by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/276
* release: v0.6.1-beta by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/280
* release: v0.6.1-beta by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/282
* chore: release by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/283
* feat: Posthog analytics setup and integrations page by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/284
* feat: added more integrations eg: github, linear, slack etc. by @Dhruv-Maradiya in https://github.com/theexperiencecompany/gaia/pull/271
* release: v0.7.0-beta by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/285
* chore(release): add fallback release-please config and update workflow by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/286


**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.6.0...v0.7.0

## 0.6.1 (2025-11-07)

## What's Changed
* fix: Dexie fetching uses batch syncing & sidebar state updation by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/276
* release: v0.6.1-beta by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/280
* release: v0.6.1-beta by @aryanranderiya in https://github.com/theexperiencecompany/gaia/pull/282


**Full Changelog**: https://github.com/theexperiencecompany/gaia/compare/v0.6.0...v0.6.1

## [0.6.0](https://github.com/theexperiencecompany/gaia/compare/v0.5.1...v0.6.0) (2025-11-07)


### Features

* add menu accordion state management to UI store ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
* add menu accordion state management to UI store ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
* Better Web Search & Webpage Fetch ([#256](https://github.com/theexperiencecompany/gaia/issues/256)) ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
* enhance SidebarTopButtons with accordion for menu items ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
* enhance SidebarTopButtons with accordion for menu items ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
* improved caching decorators with type-safe model support ([#232](https://github.com/theexperiencecompany/gaia/issues/232)) ([813b631](https://github.com/theexperiencecompany/gaia/commit/813b6311b1a6edeb92c24465c8943a995278ae74))
* Minor onboarding & memory improvements ([#251](https://github.com/theexperiencecompany/gaia/issues/251)) ([9c3da0e](https://github.com/theexperiencecompany/gaia/commit/9c3da0e7bc38df99f8d6cef4e060ded169510682))
* More ai calendar stuff ([#275](https://github.com/theexperiencecompany/gaia/issues/275)) ([46cfc1b](https://github.com/theexperiencecompany/gaia/commit/46cfc1b98d26090cdb2e19dc3de0441157663e6e))
* New calendar page & updated tools ([#265](https://github.com/theexperiencecompany/gaia/issues/265)) ([5fe18b3](https://github.com/theexperiencecompany/gaia/commit/5fe18b3dedfdf2f99dd31aa42c6ec5918fac9841))
* Replace web search from deprecated bing API with Tavily & replace manual playwright fetching with firecrawl ([#254](https://github.com/theexperiencecompany/gaia/issues/254)) ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
* Separate Public workflows page with programmatic SEO ([#266](https://github.com/theexperiencecompany/gaia/issues/266)) ([2874591](https://github.com/theexperiencecompany/gaia/commit/287459150787ffd14159177cf8c83f27a507b385))
* speed up follow-up actions by streaming in background  ([#242](https://github.com/theexperiencecompany/gaia/issues/242)) ([e94ed6c](https://github.com/theexperiencecompany/gaia/commit/e94ed6cff4194f92f3cdc1263219e2f679fd352e))
* sub-graph system implemented ([#259](https://github.com/theexperiencecompany/gaia/issues/259)) ([f2d362d](https://github.com/theexperiencecompany/gaia/commit/f2d362d086d7f59784f972d27f6075f6ad54a366))
* update dependencies for firecrawl and tavily ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
* update dependencies for firecrawl and tavily ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
* update OAuth and model configurations to use local icon assets ([#239](https://github.com/theexperiencecompany/gaia/issues/239)) ([79bdab9](https://github.com/theexperiencecompany/gaia/commit/79bdab93d38d2d1eef88f9b12930d43f301d4591))


### Bug Fixes

* Calendar Events & Mails not fetching on Chat Page ([#243](https://github.com/theexperiencecompany/gaia/issues/243)) ([5a861fa](https://github.com/theexperiencecompany/gaia/commit/5a861fa3de490a52fba74fe5710c058ff1676834))
* correct metadata key from 'silence' to 'silent' in execute_graph_streaming function ([f54ceb3](https://github.com/theexperiencecompany/gaia/commit/f54ceb3a6f72473f9bdf24bb4e17fa81184ef8bc))
* Don't install uvloop on Windows ([#249](https://github.com/theexperiencecompany/gaia/issues/249)) ([c0f4cb4](https://github.com/theexperiencecompany/gaia/commit/c0f4cb4e86ed3877b6774c126a152bca4a056c19))


### Documentation

* update docs for the new infisical setup ([185861b](https://github.com/theexperiencecompany/gaia/commit/185861bf2ad7a8753d8af45efe9fc7ac967f806d))
* update docs for the new infisical setup ([2e72e6b](https://github.com/theexperiencecompany/gaia/commit/2e72e6b3cf4d68219a7d6ed21d5d83f13bd6d1ef))
