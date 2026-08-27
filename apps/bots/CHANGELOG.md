# Changelog

## [1.6.0](https://github.com/theexperiencecompany/gaia/compare/bots-v1.5.0...bots-v1.6.0) (2026-08-25)


### Features

* agent-first harness — deterministic e2e testing, direct agent invocation, and a leaner CI ([#877](https://github.com/theexperiencecompany/gaia/issues/877)) ([16d7e7e](https://github.com/theexperiencecompany/gaia/commit/16d7e7e494b54c1188d66024cae3df1b786e4423))
* **analytics:** unify PostHog identity on stable user IDs and add core event capture ([#1007](https://github.com/theexperiencecompany/gaia/issues/1007)) ([45e843d](https://github.com/theexperiencecompany/gaia/commit/45e843d4bb7519a3849a7b1491395b1ba9cc4665))
* **bots:** iMessage platform via Photon/Spectrum with Pro gating ([#1016](https://github.com/theexperiencecompany/gaia/issues/1016)) ([8b054d9](https://github.com/theexperiencecompany/gaia/commit/8b054d999ca3791fc9bf141a581a0cbac1a1a4fd))
* **dev:** flag-based dev auth bypass, real login by default ([#883](https://github.com/theexperiencecompany/gaia/issues/883)) ([2c70109](https://github.com/theexperiencecompany/gaia/commit/2c70109bdf5ea087c91a5cf57df2a15e34501170))
* **devx:** ci:local, ci:remote, pr:comments — agent-legible shipping gates ([#1093](https://github.com/theexperiencecompany/gaia/issues/1093)) ([efd45e0](https://github.com/theexperiencecompany/gaia/commit/efd45e0960831e5e729703f6d891ddddda9679c4))
* Extract PDF/DOCX/XLSX/PPTX/CSV locally via anydoc + pdf-inspector ([#890](https://github.com/theexperiencecompany/gaia/issues/890)) ([e6c71c4](https://github.com/theexperiencecompany/gaia/commit/e6c71c4285347c134a5db6857cb46926033e97c6))
* **gmail:** inbox summary tool, body normalization, and agent docs ([#783](https://github.com/theexperiencecompany/gaia/issues/783)) ([0edf4a4](https://github.com/theexperiencecompany/gaia/commit/0edf4a4e9e705e337d52cb6502c184da4d3d1144))
* **mobile:** unified streaming tool chain with subagent + HIL visibility, card contract sweep ([#1098](https://github.com/theexperiencecompany/gaia/issues/1098)) ([0924ce2](https://github.com/theexperiencecompany/gaia/commit/0924ce2e77dfab5643e719e379cf7892de33240e))
* **observability:** wide-event enforcement across all surfaces — evlog gates, Babel bots scanner, min-score rework, gate simplification ([#884](https://github.com/theexperiencecompany/gaia/issues/884)) ([5040dca](https://github.com/theexperiencecompany/gaia/commit/5040dca5373f11f28394d234469e4d1c3cd6fb45))


### Bug Fixes

* **agents:** root-cause fixes for Telegram reply quality, memory hygiene, executor grounding and bot sessions ([#1094](https://github.com/theexperiencecompany/gaia/issues/1094)) ([11995af](https://github.com/theexperiencecompany/gaia/commit/11995af04d752a6025d4c7d4ec998138ecaf0f95))
* **api:** drop removed ast aliases so config schema dump works on Python 3.12+ ([#878](https://github.com/theexperiencecompany/gaia/issues/878)) ([beebc92](https://github.com/theexperiencecompany/gaia/commit/beebc92c7b97487dcbc8ff5004932c43b3e45281))
* **bots:** ship the grpc peer deps the photon sdk resolves at runtime ([#1049](https://github.com/theexperiencecompany/gaia/issues/1049)) ([f0e211b](https://github.com/theexperiencecompany/gaia/commit/f0e211bfa412c61b70ad2ccae31b740ba51ecdb8))
* **bots:** stop the imessage bundle colliding on createRequire ([#1048](https://github.com/theexperiencecompany/gaia/issues/1048)) ([dc94d99](https://github.com/theexperiencecompany/gaia/commit/dc94d9956fe0909c4e5527b9929a5dba01270c4d))
* **bots:** stop truncating replies and losing bubbles; one splitter for message breaks ([#1051](https://github.com/theexperiencecompany/gaia/issues/1051)) ([c542095](https://github.com/theexperiencecompany/gaia/commit/c5420959cecab7a55fdf7f7879aa0fd827189461))
* **ci:** publish versioned imessage bot images so the deploy can pin them ([#1050](https://github.com/theexperiencecompany/gaia/issues/1050)) ([19ec4c1](https://github.com/theexperiencecompany/gaia/commit/19ec4c114280bf850985af7729ca9352ddafe835))
* **ci:** register bot projects as docker releases so they get immutable tags ([#1011](https://github.com/theexperiencecompany/gaia/issues/1011)) ([2b1d208](https://github.com/theexperiencecompany/gaia/commit/2b1d2087b17fae78c7ce26b17309a36528fb7875))
* **quality:** repair lint errors blocking the PR quality gate ([#870](https://github.com/theexperiencecompany/gaia/issues/870)) ([d4b5605](https://github.com/theexperiencecompany/gaia/commit/d4b56055eb6e3e938f2dd2e85ba36c28f7d2bdce))
* **security:** remediate 192 of 196 Dependabot alerts ([#860](https://github.com/theexperiencecompany/gaia/issues/860)) ([9984705](https://github.com/theexperiencecompany/gaia/commit/99847059fee66f46c6a7f94cd3569047f4eec470))
* **security:** remediate audited SSRF/IDOR/auth/webhook findings across the monorepo ([#848](https://github.com/theexperiencecompany/gaia/issues/848)) ([13f36fc](https://github.com/theexperiencecompany/gaia/commit/13f36fc07485d47b99f68d9e9e8b291d6aa1101c))
* **workflows:** JSON-safe tool payloads, reschedule-safe scheduled fires, break-sentinel variants ([#1067](https://github.com/theexperiencecompany/gaia/issues/1067)) ([0aa3d54](https://github.com/theexperiencecompany/gaia/commit/0aa3d54dd8ef0655fbd8a624fa315bcd8a1cb3a8))


### Performance Improvements

* **cache:** keep the prompt prefix stable so conversations actually hit the provider cache ([#1025](https://github.com/theexperiencecompany/gaia/issues/1025)) ([a44916d](https://github.com/theexperiencecompany/gaia/commit/a44916ddbf70ef6b1e605d20dcf91eb2049a4264))
* **ci:** PR gate 13.4m→8.9m; parallel gate-safe master docker phase; GHCR registry layer cache ([#1064](https://github.com/theexperiencecompany/gaia/issues/1064)) ([46b5ecc](https://github.com/theexperiencecompany/gaia/commit/46b5eccdcd9c7ac114a7bacf482e2a346bd601c2))
* Docker layer cache moves from type=gha to GHCR type=registry ([46b5ecc](https://github.com/theexperiencecompany/gaia/commit/46b5eccdcd9c7ac114a7bacf482e2a346bd601c2))


### Reverts

* .next/cache seeding into the docker-web context (9a49586ca + ([46b5ecc](https://github.com/theexperiencecompany/gaia/commit/46b5eccdcd9c7ac114a7bacf482e2a346bd601c2))

## [1.5.0](https://github.com/theexperiencecompany/gaia/compare/bots-v1.4.1...bots-v1.5.0) (2026-07-03)


### Features

* **logging:** greppable subsystem prefixes + structured wide events ([#815](https://github.com/theexperiencecompany/gaia/issues/815)) ([b4fca50](https://github.com/theexperiencecompany/gaia/commit/b4fca508e9a0bcb559c89d1d57bafde82b04e3f2))
* **workflow:** deliver results into linked platform chats as real messages ([#827](https://github.com/theexperiencecompany/gaia/issues/827)) ([02d3c30](https://github.com/theexperiencecompany/gaia/commit/02d3c301a8f144e6fd4e69d408e4eba2d2a99fe0))

## [1.4.1](https://github.com/theexperiencecompany/gaia/compare/bots-v1.4.0...bots-v1.4.1) (2026-06-21)


### Bug Fixes

* **bots:** copy pnpm patches into Docker build context ([#770](https://github.com/theexperiencecompany/gaia/issues/770)) ([66a4f43](https://github.com/theexperiencecompany/gaia/commit/66a4f43b0428d9a161f78876bfdd60b2a2019bc1))
* **whatsapp:** send template fallback on any free-form failure ([#790](https://github.com/theexperiencecompany/gaia/issues/790)) ([ca73bab](https://github.com/theexperiencecompany/gaia/commit/ca73babc2c6ef0db575da2793bb318ee50560c97))

## [1.4.0](https://github.com/theexperiencecompany/gaia/compare/bots-v1.3.0...bots-v1.4.0) (2026-06-12)


### Features

* **api:** add notification agent tools ([#662](https://github.com/theexperiencecompany/gaia/issues/662)) ([82ca761](https://github.com/theexperiencecompany/gaia/commit/82ca761b59df444dcfc5dca5c250e945621f2420))
* **bots:** add structured lifecycle and event logging ([#625](https://github.com/theexperiencecompany/gaia/issues/625)) ([7b76163](https://github.com/theexperiencecompany/gaia/commit/7b76163bd8a8a78b83a77ade8a77fd59ee25f9a4))
* **bots:** add structured lifecycle and event logging ([#625](https://github.com/theexperiencecompany/gaia/issues/625)) ([#626](https://github.com/theexperiencecompany/gaia/issues/626)) ([8b417b4](https://github.com/theexperiencecompany/gaia/commit/8b417b462f35cc0a95d6848118961afc79329c72))
* **bots:** direct bot endpoints with shared BotServer ([#627](https://github.com/theexperiencecompany/gaia/issues/627)) ([357ad28](https://github.com/theexperiencecompany/gaia/commit/357ad289a9d05c19ed63e3a3dc8dc6c48e6b318c))
* **bots:** WhatsApp + Telegram media & voice support, with cross-cutting bot and API fixes ([#688](https://github.com/theexperiencecompany/gaia/issues/688)) ([80c67cc](https://github.com/theexperiencecompany/gaia/commit/80c67cc388403860b457674b7519c29903bc151c))
* deliver agent-generated files to bot users + docgen skill migration ([#734](https://github.com/theexperiencecompany/gaia/issues/734)) ([b71c062](https://github.com/theexperiencecompany/gaia/commit/b71c062054c62e6809651081c858d9bb9b484928))
* RabbitMQ outbound delivery to bots + self-managing agent workspace ([#729](https://github.com/theexperiencecompany/gaia/issues/729)) ([a02b1fd](https://github.com/theexperiencecompany/gaia/commit/a02b1fdd40c29e2893335f5e6838f856d7fb9950))
* **web:** landing page copy, navbar, and comparison grid overhaul ([#674](https://github.com/theexperiencecompany/gaia/issues/674)) ([7e2062d](https://github.com/theexperiencecompany/gaia/commit/7e2062da2ba0f5c9a3fc082bf8abc061c8348f36))


### Bug Fixes

* **bots:** address CodeRabbit review comments ([7599de7](https://github.com/theexperiencecompany/gaia/commit/7599de753168257777bf117421a99ae86ffd0f63))
* platform-aware markdown formatting and OpenUI gating ([#647](https://github.com/theexperiencecompany/gaia/issues/647)) ([82de0e2](https://github.com/theexperiencecompany/gaia/commit/82de0e205b466784d3d4d20de4f1715a7ecc7f02))
* **security:** patch 6 high-confidence vulnerabilities from audit ([#656](https://github.com/theexperiencecompany/gaia/issues/656)) ([a24cf7d](https://github.com/theexperiencecompany/gaia/commit/a24cf7d1d0c8d037f23457da23450e76916ca11b))
* **sonar:** resolve SonarQube quality-gate findings for develop→master ([#738](https://github.com/theexperiencecompany/gaia/issues/738)) ([af0be97](https://github.com/theexperiencecompany/gaia/commit/af0be97dcebf3ef7f307d4172123aa47a4c8905a))
* **whatsapp:** deterministic typing indicator and welcome message ([#643](https://github.com/theexperiencecompany/gaia/issues/643)) ([83f42c3](https://github.com/theexperiencecompany/gaia/commit/83f42c395d1dd2f8584b625d5cbb72484d29e5e1))

## [1.3.0](https://github.com/theexperiencecompany/gaia/compare/bots-v1.2.0...bots-v1.3.0) (2026-04-05)


### Features

* add tsup configuration for Discord, Slack, and Telegram bots ([3a5d164](https://github.com/theexperiencecompany/gaia/commit/3a5d1641742584b807b8d10b53c632d89f7b64e8))
* add tsup configuration for Discord, Slack, and Telegram bots ([#541](https://github.com/theexperiencecompany/gaia/issues/541)) ([67d2cc2](https://github.com/theexperiencecompany/gaia/commit/67d2cc2daffe8900fb0cac6e5707adf7ccda795e))
* **analytics:** add PostHog analytics to bots ([#599](https://github.com/theexperiencecompany/gaia/issues/599)) ([af894bf](https://github.com/theexperiencecompany/gaia/commit/af894bfe8a1bdeacbb99c6ccea487d3b8ac14554))
* **analytics:** add PostHog analytics to bots and CLI ([8d799ef](https://github.com/theexperiencecompany/gaia/commit/8d799ef56f0f789f9ceb660ae0f6ab2eb01bb518))
* **ci:** Dagger integration test overhaul — real-service tests + CI hardening ([#591](https://github.com/theexperiencecompany/gaia/issues/591)) ([7736c39](https://github.com/theexperiencecompany/gaia/commit/7736c3957b73b51e9e47291836c61a6f03e750bd))
* **whatsapp:** integrate WhatsApp via Kapso ([#581](https://github.com/theexperiencecompany/gaia/issues/581)) ([c870d16](https://github.com/theexperiencecompany/gaia/commit/c870d16ef63cc103c6ce465cf029f17b449c91a3))


### Bug Fixes

* Build and publish bot Docker images to GHCR ([#531](https://github.com/theexperiencecompany/gaia/issues/531)) ([bcb350f](https://github.com/theexperiencecompany/gaia/commit/bcb350f2c10a8f908ccb3bafea66537851ba2745))


### Performance Improvements

* remove barrel exports for faster HMR and build times ([#569](https://github.com/theexperiencecompany/gaia/issues/569)) ([70388ff](https://github.com/theexperiencecompany/gaia/commit/70388ffb681f6910e11dfae8d005825ceee4285e))

## [1.2.0](https://github.com/theexperiencecompany/gaia/compare/bots-v1.1.0...bots-v1.2.0) (2026-02-27)


### Features

* optimize Docker images, prune unused API deps, fix landing timezone ([1fc1a46](https://github.com/theexperiencecompany/gaia/commit/1fc1a464e691a7db85937db64b7ebf1b2fdd1c21))
* optimize Docker images, prune unused API deps, fix landing timezone ([#524](https://github.com/theexperiencecompany/gaia/issues/524)) ([5acd831](https://github.com/theexperiencecompany/gaia/commit/5acd8313e1067a22da66d5bb90dcf2ff545ae9b7))


### Bug Fixes

* Adjust ownership and permissions in Dockerfiles for better user access ([99637d6](https://github.com/theexperiencecompany/gaia/commit/99637d68c58cff970b7e7f3fbd9c1f38712ea109))
* update package dependencies and add new cloudflare config files ([#507](https://github.com/theexperiencecompany/gaia/issues/507)) ([ae0fccd](https://github.com/theexperiencecompany/gaia/commit/ae0fccd9853ad0582b491e9a2f5d5f6e06faa136))
* update package dependencies and add new cloudflare configuration files ([7ff4a3c](https://github.com/theexperiencecompany/gaia/commit/7ff4a3c1b189ff59573928d94925afeb1a761214))

## [1.1.0](https://github.com/theexperiencecompany/gaia/compare/bots-v1.0.0...bots-v1.1.0) (2026-02-23)


### Features

* Add Bots, CLI, Added skills in codebase ([#487](https://github.com/theexperiencecompany/gaia/issues/487)) ([206675b](https://github.com/theexperiencecompany/gaia/commit/206675bf79e41da50e9f1870e854783a22dee785))
* add Discord DM support and NEW_MESSAGE_BREAK handling ([735fcc3](https://github.com/theexperiencecompany/gaia/commit/735fcc3c6705778d185584afa155886aaae4f07b))
* Add integration status to API responses and display it in bot settings, fetching all user integrations. ([7153447](https://github.com/theexperiencecompany/gaia/commit/71534470e10e41e4c04db227e8adfd5e2a4e947f))
* Add Telegram bot, enhance platform linking with user profile data, and centralize bot command documentation. ([d8a3b55](https://github.com/theexperiencecompany/gaia/commit/d8a3b55da6c97403d196a193eb92b725ced656be))
* **bots:** Enhance Discord bot with rotating presence, DM welcome message, and context menu commands ([29ed4b7](https://github.com/theexperiencecompany/gaia/commit/29ed4b77a377e0be9fa7836da9295a188285635b))
* **bots:** implement comprehensive bot platform integrations ([287e62c](https://github.com/theexperiencecompany/gaia/commit/287e62c3731f2edd4e5ef606a10ca16b58ac195f))
* **bots:** implement security hardening and UX enhancements ([d93e3c4](https://github.com/theexperiencecompany/gaia/commit/d93e3c42af1e79b79db1acdaab3c1b9f43d6608a))
* **bots:** remove test targets from Discord, Slack, and Telegram bot configurations; add bots-e2e package and project configurations ([63e6ef4](https://github.com/theexperiencecompany/gaia/commit/63e6ef470f73f3837ab24df756ab8ffcc587e363))
* Enhance bot streaming stability and implementation, add Discord bot landing page, and update bot documentation. ([82024be](https://github.com/theexperiencecompany/gaia/commit/82024be147391761b2f6f88168d77d9e0739eb61))
* Enhance Discord auth command with deferral and existing link check, and update conversation URL paths from `/chat/` to `/c/`. ([236f9f4](https://github.com/theexperiencecompany/gaia/commit/236f9f4b9b0cfa5e7a0402abe2df4215e1b7d225))
* enhance message handling in bots to support dynamic updates and new message breaks ([e3e270b](https://github.com/theexperiencecompany/gaia/commit/e3e270b67153fd8b77190f0c09c3d326299cbfc3))
* Implement bot API key authentication middleware and add Discord help and settings commands. ([a5549e9](https://github.com/theexperiencecompany/gaia/commit/a5549e9ee16a7686c96cba365cbb28b75bce5d46))
* implement centralized bot configuration with Infisical secret injection and consolidate `.env.example` files. ([fb8c3ad](https://github.com/theexperiencecompany/gaia/commit/fb8c3add4ca372c2abd2e1dcbfbb629798878a41))
* Implement secure platform linking using link tokens and enhance WorkOS SSO with return URL handling. ([d0b1caf](https://github.com/theexperiencecompany/gaia/commit/d0b1caf7b72716d24ee740abdf2dca2eee1c7923))
* Improve docs structure and styling ([#489](https://github.com/theexperiencecompany/gaia/issues/489)) ([3a93bab](https://github.com/theexperiencecompany/gaia/commit/3a93bab27e25bd58401aedc3ab8a4f1d55f2974b))
* Improve docs structure and styling ([#489](https://github.com/theexperiencecompany/gaia/issues/489)) ([#490](https://github.com/theexperiencecompany/gaia/issues/490)) ([17c9475](https://github.com/theexperiencecompany/gaia/commit/17c94755e9f4b1160ff469eb166f5f042baa96da))
* integrate bots into Nx, CI pipeline, and release system ([4a4019b](https://github.com/theexperiencecompany/gaia/commit/4a4019b381eec943a0f79538a032df8719946431))
* Introduce `/stop` and `/unlink` bot commands with supporting API endpoint and documentation updates. ([eabf7e7](https://github.com/theexperiencecompany/gaia/commit/eabf7e72844dc0ea59170ec8c77f9580ccdf99ce))
* Introduce initial implementations for Discord, Slack, and Telegram bots with supporting API endpoints and shared utilities. ([08f3b55](https://github.com/theexperiencecompany/gaia/commit/08f3b55cbd36771c212a15787f8ab3b882d3d15d))
* Introducing GAIA bots ([#485](https://github.com/theexperiencecompany/gaia/issues/485)) ([c47c6b8](https://github.com/theexperiencecompany/gaia/commit/c47c6b839484181a0b465b87a11261ed4e83cc70))
* Public Integrations and MCP with Marketplace page ([#430](https://github.com/theexperiencecompany/gaia/issues/430)) ([1ba6055](https://github.com/theexperiencecompany/gaia/commit/1ba6055f8d81c223d33ffc89d0ece1a6d28fa74b))
* remove weather and search commands from Discord, Slack, Telegram, and WhatsApp bots. ([e21e46a](https://github.com/theexperiencecompany/gaia/commit/e21e46ae566f92372e4705e95713c77546f9833b))
* serialize Telegram message updates, improve Markdown parsing error handling, and refine streaming message break logic ([47390ec](https://github.com/theexperiencecompany/gaia/commit/47390ec2e7a277a2b7cf331f322636c2fac90842))


### Bug Fixes

* **bots:** add public context restriction, mention stripping, and rate limit UX ([ac553fb](https://github.com/theexperiencecompany/gaia/commit/ac553fbc71fcd4f550e27fedf65a07bd9802816a))
* **bots:** Comprehensive audit — fix deployment, security, and functional bugs ([e83a7b7](https://github.com/theexperiencecompany/gaia/commit/e83a7b7b590c512827541567c94c4d12797aef8c))
* implement /new command and resolve Discord bot timeout issues ([eab9872](https://github.com/theexperiencecompany/gaia/commit/eab9872fb530aaf255d379d741c287e5357673b5))
* remove streaming thinking... in discord. ([aa9ce8e](https://github.com/theexperiencecompany/gaia/commit/aa9ce8e28d657ab65c9939a30e4d0979b9c2674d))
* update docker build command to include missing image tag ([e5298cd](https://github.com/theexperiencecompany/gaia/commit/e5298cd8d4ec9870f5af915bd91b8d056f1bd2f7))
* update docker build command to include missing image tag ([#500](https://github.com/theexperiencecompany/gaia/issues/500)) ([95a9323](https://github.com/theexperiencecompany/gaia/commit/95a932314bf6de615511cdf62f9f57dcaf7666af))
* update docker build commands for discord, slack, and telegram bots ([0aef2da](https://github.com/theexperiencecompany/gaia/commit/0aef2dada30ad51c43e6594452b4c2a2ac9ecbf6))
