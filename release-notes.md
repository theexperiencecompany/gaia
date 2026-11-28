:robot: I have created a release *beep* *boop*
---


<details><summary>api: 0.26.0</summary>

## [0.26.0](https://github.com/theexperiencecompany/gaia/compare/api-v0.25.0...api-v0.26.0) (2026-11-28)


### Features

* **agents:** one invocation layer records every tool call a run makes ([#1618](https://github.com/theexperiencecompany/gaia/issues/1618)) ([65ce329](https://github.com/theexperiencecompany/gaia/commit/65ce329de5de797ec64141f5f7be465b75dd7838))
* **agents:** outcome-ownership POC (ambiguity ladder, verified outcomes, tracked-todo ownership) ([#1562](https://github.com/theexperiencecompany/gaia/issues/1562)) ([0967be8](https://github.com/theexperiencecompany/gaia/commit/0967be84ce3e064ee9cdb49523245b4de0b1c1c0))
* **analytics:** workflow:created carries its origin; activation counts only asked-for workflows ([#1603](https://github.com/theexperiencecompany/gaia/issues/1603)) ([507412c](https://github.com/theexperiencecompany/gaia/commit/507412c3983cab065e2fae9416a4b5dd06f18141))
* **api:** a restarted bot resumes the events stream after what it delivered, and voice reads wire 2 ([#1958](https://github.com/theexperiencecompany/gaia/issues/1958)) ([b83dd4b](https://github.com/theexperiencecompany/gaia/commit/b83dd4bb7659762766ab433af0f6eb5db6883947))
* **api:** a stream's request event carries its real bytes, and the bots log their git commit ([#1946](https://github.com/theexperiencecompany/gaia/issues/1946)) ([2bc8074](https://github.com/theexperiencecompany/gaia/commit/2bc807406db36877aaaff59d65cc69d6b13caab6))
* **api:** inbox desk briefs once a day and says what needs you ([#1668](https://github.com/theexperiencecompany/gaia/issues/1668)) ([4abf4d0](https://github.com/theexperiencecompany/gaia/commit/4abf4d0224d54c51df1de7ddf67cb375b0697d89))
* **api:** inbox desk briefs once a day from per-account mail subagents ([4abf4d0](https://github.com/theexperiencecompany/gaia/commit/4abf4d0224d54c51df1de7ddf67cb375b0697d89))
* **api:** resume a chat, todo or workflow once the user connects or configures what it asked for ([#1779](https://github.com/theexperiencecompany/gaia/issues/1779)) ([e99a935](https://github.com/theexperiencecompany/gaia/commit/e99a935b339fd666c409883d9093ac413b6fd8d2))
* **api:** run every LLM role on Cloudflare Workers AI when it is configured ([#1771](https://github.com/theexperiencecompany/gaia/issues/1771)) ([c4990f0](https://github.com/theexperiencecompany/gaia/commit/c4990f077e527a1349dcd32275ae55ab144dfc09))
* **api:** thread todos stay quiet when they resolve, and reopen when the thread comes back ([#1688](https://github.com/theexperiencecompany/gaia/issues/1688)) ([b455c9d](https://github.com/theexperiencecompany/gaia/commit/b455c9dbded8e1dfa893ae8d549a24532acb1f84))
* **api:** tool cards older than 30 days drop their stored outputs and thinking ([#1979](https://github.com/theexperiencecompany/gaia/issues/1979)) ([13e6dee](https://github.com/theexperiencecompany/gaia/commit/13e6deeb49c0432be21d526bfe12746cc40d28b7))
* **briefing:** briefing:sent says when code salvaged the composition or the voice ([#1915](https://github.com/theexperiencecompany/gaia/issues/1915)) ([6c14938](https://github.com/theexperiencecompany/gaia/commit/6c14938d755da084a5c29be7fb642dc3908113f6))
* **briefing:** daily and weekly briefs, heygaia.link sharing, and OpenUI artifacts ([#1853](https://github.com/theexperiencecompany/gaia/issues/1853)) ([b0c7d7c](https://github.com/theexperiencecompany/gaia/commit/b0c7d7c38edec5d4d4e7a1b497b792efe5b925ec))
* **browser:** Jev behind the BROWSER_JEV experimental flag, off by default ([#1601](https://github.com/theexperiencecompany/gaia/issues/1601)) ([8344553](https://github.com/theexperiencecompany/gaia/commit/8344553f9e5bd5b3d640bd5c7c43701748e30a1c))
* **browser:** run the Chromium host on Fortress as an opt-in alternative ([#1610](https://github.com/theexperiencecompany/gaia/issues/1610)) ([0c4cea5](https://github.com/theexperiencecompany/gaia/commit/0c4cea5b599e8f27dd4ce93a6873ce6074745c1c))
* **ci:** nx decides what CI runs; stop the self-made flakes and silent passes ([#1569](https://github.com/theexperiencecompany/gaia/issues/1569)) ([c722c9c](https://github.com/theexperiencecompany/gaia/commit/c722c9c021df2a050773dfe34cb2d9040bed2aeb))
* **conversation:** the conversation-runtime redesign (stack [#1716](https://github.com/theexperiencecompany/gaia/issues/1716)[#1723](https://github.com/theexperiencecompany/gaia/issues/1723), landed as one) ([#1723](https://github.com/theexperiencecompany/gaia/issues/1723)) ([8ff2293](https://github.com/theexperiencecompany/gaia/commit/8ff2293d14eb97e6fba582ba1b1fdb9dc3a99730))
* **delivery:** presence-aware, one-place proactive messaging ([#1523](https://github.com/theexperiencecompany/gaia/issues/1523)) ([39887cf](https://github.com/theexperiencecompany/gaia/commit/39887cfe9e9fe0b6c7a1fe5daa916cf09eac2b2f))
* **evals:** the trigger gate's accuracy on 420 labelled emails, regraded in CI ([#1658](https://github.com/theexperiencecompany/gaia/issues/1658)) ([5bc4c7b](https://github.com/theexperiencecompany/gaia/commit/5bc4c7b6c8cd2d191c256a160b70ee261975bfe1))
* **inbox:** JEV buckets the desk's mail into reply, waiting, act, fyi and junk; gate skips stay bounded ([#1667](https://github.com/theexperiencecompany/gaia/issues/1667)) ([29f0697](https://github.com/theexperiencecompany/gaia/commit/29f0697a512c1d0fcd8037c49e2795f21073bbe3))
* **inbox:** one JEV verdict per email, read by the desk gate on arrival and by the sweep ([#1671](https://github.com/theexperiencecompany/gaia/issues/1671)) ([f22cfd0](https://github.com/theexperiencecompany/gaia/commit/f22cfd029d0d119f06d68c187118cdbd9ab1ded5))
* **notifications:** notifications expire 90 days after they are created ([#1973](https://github.com/theexperiencecompany/gaia/issues/1973)) ([441b55a](https://github.com/theexperiencecompany/gaia/commit/441b55af64c00bf16a60410a3679e0abb11216bf))
* **observability:** every alert rule reaches prod, every user-facing failure has a signal, and alerts name what broke ([#1911](https://github.com/theexperiencecompany/gaia/issues/1911)) ([e8ea875](https://github.com/theexperiencecompany/gaia/commit/e8ea8752ea7eda08d6a0d36681ebf7fb41553e32))
* **onboarding:** ask where the user heard about GAIA ([#1967](https://github.com/theexperiencecompany/gaia/issues/1967)) ([197f123](https://github.com/theexperiencecompany/gaia/commit/197f123ee928733f96d947979a43bd7066749f02))
* **onboarding:** first conversations users can trust, in their language ([#1584](https://github.com/theexperiencecompany/gaia/issues/1584)) ([9326f82](https://github.com/theexperiencecompany/gaia/commit/9326f82aaf40dfd220c99d8fb7d9a1ff6ea0b241))
* **payments:** open Dodo checkout as one page, wallets first ([#1657](https://github.com/theexperiencecompany/gaia/issues/1657)) ([68789b8](https://github.com/theexperiencecompany/gaia/commit/68789b8a94eb0ad576fc4368a5f43fe81f05e1ab))
* **playbooks:** a playbook is picked from the run record, not retyped ([#1619](https://github.com/theexperiencecompany/gaia/issues/1619)) ([0e7d4f5](https://github.com/theexperiencecompany/gaia/commit/0e7d4f51b7cc2c9bd7bce871cfb48f1a5224a005))
* **playbooks:** a workflow is asked on every run until it has a playbook ([#1608](https://github.com/theexperiencecompany/gaia/issues/1608)) ([6c58ac7](https://github.com/theexperiencecompany/gaia/commit/6c58ac783b2f50368f491ded4c60f0a884b92a1e))
* **playbooks:** every prod write since September replays in CI; the first refusal pages ([#1620](https://github.com/theexperiencecompany/gaia/issues/1620)) ([d444347](https://github.com/theexperiencecompany/gaia/commit/d44434748e6f72d82ad6b122af93cb10da721f52))
* **settings:** open a linked Telegram, WhatsApp or iMessage chat from linked accounts ([#1633](https://github.com/theexperiencecompany/gaia/issues/1633)) ([b6eb365](https://github.com/theexperiencecompany/gaia/commit/b6eb36542021563f8dfbaa855b9763f0ce4f955e))
* **settings:** quiet hours are the user's own, set on a noon-to-noon slider ([#1664](https://github.com/theexperiencecompany/gaia/issues/1664)) ([074b108](https://github.com/theexperiencecompany/gaia/commit/074b1089d6e92d0b64988fbcdbf4b53f13db9939))
* **todos:** give every tracked todo its own chat, led by what woke each run ([#1561](https://github.com/theexperiencecompany/gaia/issues/1561)) ([7fa8464](https://github.com/theexperiencecompany/gaia/commit/7fa84648be37066f58b4929dc0f8a0c468d8f1f9))
* **todos:** the Inbox desk wakes only for mail that may need you ([#1659](https://github.com/theexperiencecompany/gaia/issues/1659)) ([363779f](https://github.com/theexperiencecompany/gaia/commit/363779f4befa5088046e5cb2ac7607e9af298ea6))
* **triggers:** quiet hours hold what can wait and let through what cannot ([#1655](https://github.com/theexperiencecompany/gaia/issues/1655)) ([e672187](https://github.com/theexperiencecompany/gaia/commit/e672187cc7aeb91ebe61578a9794963edabe768c))
* **triggers:** trigger gates, one JEV check before a triggered run ([#1654](https://github.com/theexperiencecompany/gaia/issues/1654)) ([0cb2c04](https://github.com/theexperiencecompany/gaia/commit/0cb2c043ccf66602edc035966102bc630fc22ad3))
* **web:** see, edit and turn off a job's Runs only when rule ([#1661](https://github.com/theexperiencecompany/gaia/issues/1661)) ([e89213c](https://github.com/theexperiencecompany/gaia/commit/e89213c039dfe86ae238d1d0bdf0cbc8b896243a))
* **web:** the visible fixes from the heygaia.io audit ([#1539](https://github.com/theexperiencecompany/gaia/issues/1539)) ([fc67d3d](https://github.com/theexperiencecompany/gaia/commit/fc67d3d8301634b4cd807ab6e3a5ee8c18861bc1))
* **workflows:** GAIA writes a job's Runs only when condition as it creates it ([#1660](https://github.com/theexperiencecompany/gaia/issues/1660)) ([6beec4d](https://github.com/theexperiencecompany/gaia/commit/6beec4d9752b9c504d20bd6eb68907f8cc180343))
* **workflows:** Meeting Reminder and Meeting Briefing ship with a playbook; a dry run reads but never acts ([#1622](https://github.com/theexperiencecompany/gaia/issues/1622)) ([4d56b4e](https://github.com/theexperiencecompany/gaia/commit/4d56b4ed631351e985f097808ee8abd89c625122))


### Bug Fixes

* **agents:** a busy executor's absorbed user messages get their own request ceiling, and bulk reading goes to spawns ([#1752](https://github.com/theexperiencecompany/gaia/issues/1752)) ([acfce66](https://github.com/theexperiencecompany/gaia/commit/acfce665786b3ed1b9cbd8d84d34f1611b9b5b83))
* **agents:** a fresh sign-in link for an added MCP server asks no approval, no probe sends or unrequested keys, and the tap-back waits out JEV's tail ([#1974](https://github.com/theexperiencecompany/gaia/issues/1974)) ([9d59086](https://github.com/theexperiencecompany/gaia/commit/9d5908678b59692417cc6ca8a52ed2077d7ca276))
* **agents:** accept the tool inputs models actually send; one source for the playbook brief's shape ([#1580](https://github.com/theexperiencecompany/gaia/issues/1580)) ([2249885](https://github.com/theexperiencecompany/gaia/commit/22498859640ef9d954f476474d05e14e96a80bde))
* **agents:** comms hands passing details to running work instead of promising to remember them ([#1711](https://github.com/theexperiencecompany/gaia/issues/1711)) ([fc45824](https://github.com/theexperiencecompany/gaia/commit/fc45824bd5c3d85ca05b3952e59b106469de380e))
* **agents:** every model call extends the previous one on its thread, on every provider ([#1678](https://github.com/theexperiencecompany/gaia/issues/1678)) ([c4817a2](https://github.com/theexperiencecompany/gaia/commit/c4817a2f151015e252f81eeeaa1933a06c4f2b12))
* **agents:** every provider gets each tool call followed by exactly its results ([#1975](https://github.com/theexperiencecompany/gaia/issues/1975)) ([1880942](https://github.com/theexperiencecompany/gaia/commit/1880942eb13f2dd582302539234d7a7d164fdc44))
* **agents:** keep directive tags and tool narration out of replies ([#1547](https://github.com/theexperiencecompany/gaia/issues/1547)) ([15b8b3f](https://github.com/theexperiencecompany/gaia/commit/15b8b3f4730d936ca4cc2d5e0115ce3f9d627a91))
* **agents:** sweeps go to subagents that can finish them, with their integrations already active ([#1680](https://github.com/theexperiencecompany/gaia/issues/1680)) ([b9a8323](https://github.com/theexperiencecompany/gaia/commit/b9a8323d6f06059911dcf9104de24cbfd723578b))
* **analytics:** count agent-made reminders, name the plan on subscription events, drop bot chat double events ([#1607](https://github.com/theexperiencecompany/gaia/issues/1607)) ([adc60b2](https://github.com/theexperiencecompany/gaia/commit/adc60b2389eb0e41c324b1deca9b49b120fe1d76))
* **analytics:** one emitter per server event, and every event declares its e2e coverage ([#1721](https://github.com/theexperiencecompany/gaia/issues/1721)) ([c6f9781](https://github.com/theexperiencecompany/gaia/commit/c6f9781f177c8ae097f97ddd37f4c6f3799ed945))
* **analytics:** user:active means the user used GAIA, not that they signed up or hit the paywall ([#1623](https://github.com/theexperiencecompany/gaia/issues/1623)) ([6d447e7](https://github.com/theexperiencecompany/gaia/commit/6d447e7d85d7afb86f8ae418e4f1ada6c3a3d329))
* **api:** a Gemini embedding rate-limit blip no longer loses tool discovery ([#1925](https://github.com/theexperiencecompany/gaia/issues/1925)) ([c74c5fb](https://github.com/theexperiencecompany/gaia/commit/c74c5fb455cb26f2e62dd4a425729ebc6b2bd457))
* **api:** a malformed document id reads as not found instead of ending the agent turn ([#1922](https://github.com/theexperiencecompany/gaia/issues/1922)) ([835540e](https://github.com/theexperiencecompany/gaia/commit/835540e817c630ce5b1d00da892526f6c060b66a))
* **api:** a stored tool card keeps at most a bounded share of outputs and thinking ([#1971](https://github.com/theexperiencecompany/gaia/issues/1971)) ([48ea9dd](https://github.com/theexperiencecompany/gaia/commit/48ea9dd3e32df1a178ac5255cc641c6b19ceef37))
* **api:** a tool card keeps at most the output the model is given, and says when it was cut ([#1954](https://github.com/theexperiencecompany/gaia/issues/1954)) ([5d4073a](https://github.com/theexperiencecompany/gaia/commit/5d4073ad2d5f2189fbe5b1aec400d4b38d0f146d))
* **api:** an expired MCP session reconnects instead of failing every call ([#1931](https://github.com/theexperiencecompany/gaia/issues/1931)) ([d9be8c2](https://github.com/theexperiencecompany/gaia/commit/d9be8c2b4b6cc1c77d1988b5a0197d9b06eb7aa7))
* **api:** analytics_ops loads scripts/ci/analytics.py with its import path; api tests re-run when it changes ([#1825](https://github.com/theexperiencecompany/gaia/issues/1825)) ([2f075fb](https://github.com/theexperiencecompany/gaia/commit/2f075fbed3f61a6e1c8493560334014198749f73))
* **api:** connecting an MCP integration from a chat app works without a GAIA login in the browser ([#1960](https://github.com/theexperiencecompany/gaia/issues/1960)) ([1b9d5e0](https://github.com/theexperiencecompany/gaia/commit/1b9d5e000d05d387afafeb1d7fe543f10049dfb7))
* **api:** conversation store errors and exhausted model fallbacks log what failed ([#1950](https://github.com/theexperiencecompany/gaia/issues/1950)) ([fa807b3](https://github.com/theexperiencecompany/gaia/commit/fa807b344c4c582a2108ef34c84102d614a255a4))
* **api:** every write to a published integration or workflow rebuilds its public pages ([#1943](https://github.com/theexperiencecompany/gaia/issues/1943)) ([6dd943d](https://github.com/theexperiencecompany/gaia/commit/6dd943dd86d9f64f5f68db4b5b9b692c1de0a6f5))
* **api:** failed MCP tool calls and successful LLM calls log what an incident needs ([#1986](https://github.com/theexperiencecompany/gaia/issues/1986)) ([2ecc011](https://github.com/theexperiencecompany/gaia/commit/2ecc011cd7ed750a965545691d7d661ce7041935))
* **api:** failed MCP tool calls and successful LLM calls log what an incident needs; interrogate reads [@with](https://github.com/with)_doc ([2ecc011](https://github.com/theexperiencecompany/gaia/commit/2ecc011cd7ed750a965545691d7d661ce7041935))
* **api:** keep rate limiting up during a Redis outage instead of crashing every request ([#1498](https://github.com/theexperiencecompany/gaia/issues/1498)) ([bee2e4d](https://github.com/theexperiencecompany/gaia/commit/bee2e4d02fe0f9091de556d45861293b4eec65dc))
* **api:** move workflows on the retired email and calendar triggers to their successors ([#1850](https://github.com/theexperiencecompany/gaia/issues/1850)) ([046dfaf](https://github.com/theexperiencecompany/gaia/commit/046dfaf4ef99309f704d6df979ce3dd5e2acb3e1))
* **api:** read Composio's messageId spelling as the Gmail id field ([#1751](https://github.com/theexperiencecompany/gaia/issues/1751)) ([fea37f6](https://github.com/theexperiencecompany/gaia/commit/fea37f6655d6a04b77055e8a7ca485b5707c0267))
* **api:** return Gmail draft and message readbacks as Composio sends them ([#1770](https://github.com/theexperiencecompany/gaia/issues/1770)) ([9316150](https://github.com/theexperiencecompany/gaia/commit/9316150bd6f3ee9b13aa3202fba406df765f1d2a))
* **api:** run the fast lane's word search during the semantic wait ([#1852](https://github.com/theexperiencecompany/gaia/issues/1852)) ([a4ba804](https://github.com/theexperiencecompany/gaia/commit/a4ba8049379a70380fb30efacd8bef449630c59f))
* **api:** stop runaway todo workflows, duplicate meeting fires and repeated unread pages ([#1581](https://github.com/theexperiencecompany/gaia/issues/1581)) ([0620ed0](https://github.com/theexperiencecompany/gaia/commit/0620ed0cb22234132ae3d59c334d7df31c29e477))
* **api:** the last-active backfill skips usage metered to non-user actors ([#1894](https://github.com/theexperiencecompany/gaia/issues/1894)) ([76ec6cc](https://github.com/theexperiencecompany/gaia/commit/76ec6cc428f5da00058129c0e1975aa4e3372e23))
* **api:** the last-active backfill skips usage metered to non-user actors instead of crashing the release ([76ec6cc](https://github.com/theexperiencecompany/gaia/commit/76ec6cc428f5da00058129c0e1975aa4e3372e23))
* **api:** tool search works for an MCP server whose address has dots ([#1940](https://github.com/theexperiencecompany/gaia/issues/1940)) ([0722abf](https://github.com/theexperiencecompany/gaia/commit/0722abf9be80c3e71f80e98f0e0fcbe9d29c3ee3))
* **bots:** a reaction the bot had not placed is placed once after a restart ([#1962](https://github.com/theexperiencecompany/gaia/issues/1962)) ([cec9faa](https://github.com/theexperiencecompany/gaia/commit/cec9faaeb8dc603df4a0a3725fd07e40c43c9a25))
* **bots:** point every bot link at one set of handles ([#1672](https://github.com/theexperiencecompany/gaia/issues/1672)) ([68858b3](https://github.com/theexperiencecompany/gaia/commit/68858b3cc47eacf4552a860e09050958500231e1))
* **bots:** unlinking a platform account ends its bot sessions ([#1649](https://github.com/theexperiencecompany/gaia/issues/1649)) ([72c8472](https://github.com/theexperiencecompany/gaia/commit/72c84721e5499bff120b6948801eb039d920e6f7))
* **briefing:** a brief shows what needs the user, in words a stranger can read ([#1985](https://github.com/theexperiencecompany/gaia/issues/1985)) ([079e526](https://github.com/theexperiencecompany/gaia/commit/079e52670a31c9c0a6c05099fef125e4ba4b546e))
* **briefing:** a brief's fire no longer leaves an empty "Daily Briefing" chat beside Briefings ([#1999](https://github.com/theexperiencecompany/gaia/issues/1999)) ([47bbb24](https://github.com/theexperiencecompany/gaia/commit/47bbb2441ab9d7ac6e4925bbcaaee76197d45ab7))
* **briefing:** a held schema carries no size caps, and scouts fall back off a rate-limited provider ([a0274fc](https://github.com/theexperiencecompany/gaia/commit/a0274fce66c58afe8df12ede22a93cd545e95e04))
* **briefing:** a read-only scout run refuses a gated call before the approval ledger ([#1920](https://github.com/theexperiencecompany/gaia/issues/1920)) ([a9e87fe](https://github.com/theexperiencecompany/gaia/commit/a9e87fe8353adf438b3bf128f370295dfc9e9c26))
* **briefing:** brief emails load a compact image and open on one subject, and a quiet note lists unread apps in a line ([fe35b60](https://github.com/theexperiencecompany/gaia/commit/fe35b60798d5440d308618db1f58d72449f2e169))
* **briefing:** brief emails load a compact image, open on one subject, and a quiet note lists unread apps in a line ([#1952](https://github.com/theexperiencecompany/gaia/issues/1952)) ([fe35b60](https://github.com/theexperiencecompany/gaia/commit/fe35b60798d5440d308618db1f58d72449f2e169))
* **briefing:** headlines are sent back, not cut at their limit; scouts fall back off a rate-limited provider ([#1896](https://github.com/theexperiencecompany/gaia/issues/1896)) ([a0274fc](https://github.com/theexperiencecompany/gaia/commit/a0274fce66c58afe8df12ede22a93cd545e95e04))
* **briefing:** queue workflows the release arms, reclaim a killed release's claim, split render tests into their own slice ([#1899](https://github.com/theexperiencecompany/gaia/issues/1899)) ([69aa472](https://github.com/theexperiencecompany/gaia/commit/69aa472cc759d34a06b2297621bd587b597ac7e4))
* **browser:** serve the live view under /api/v1 so its socket upgrades behind every proxy ([#1578](https://github.com/theexperiencecompany/gaia/issues/1578)) ([35625ca](https://github.com/theexperiencecompany/gaia/commit/35625ca019f70c057165ac0a95d2c26780bacba8))
* **browser:** the live view names the page it shows, and a viewer that left is not closed twice ([#1833](https://github.com/theexperiencecompany/gaia/issues/1833)) ([3371aac](https://github.com/theexperiencecompany/gaia/commit/3371aacf0b47ef8c13c13904e060af3facff6eb7))
* **calendar:** read the primary calendar when the stored selection is the "primary" alias ([#1817](https://github.com/theexperiencecompany/gaia/issues/1817)) ([2b777e0](https://github.com/theexperiencecompany/gaia/commit/2b777e09d8eea164977bde32f2aa5a7f419bb624))
* **chat:** bot DM chats stay cached and sync incrementally instead of reloading in full ([#1691](https://github.com/theexperiencecompany/gaia/issues/1691)) ([3f85a3f](https://github.com/theexperiencecompany/gaia/commit/3f85a3f40c898a8319641af3f6225dca87eee365))
* **chat:** cap conversation history so a thread can't outgrow Mongo ([#1551](https://github.com/theexperiencecompany/gaia/issues/1551)) ([c98a708](https://github.com/theexperiencecompany/gaia/commit/c98a7089334e0f9d48771c657617113a1026534d))
* **checkout:** keep the Dodo overlay in the app and never strand a payer ([#1587](https://github.com/theexperiencecompany/gaia/issues/1587)) ([ae8550b](https://github.com/theexperiencecompany/gaia/commit/ae8550bc4f5da7ae743ae24e6baac4ab06e89bbc))
* **ci:** let a browser-stack scenario pass on its flake-gate rerun ([#1634](https://github.com/theexperiencecompany/gaia/issues/1634)) ([bec8727](https://github.com/theexperiencecompany/gaia/commit/bec8727f7eefb38048b02ac041d3be5663793a1d))
* **ci:** stop six tooling traps agents hit landing a stacked PR ([#1730](https://github.com/theexperiencecompany/gaia/issues/1730)) ([7371fe8](https://github.com/theexperiencecompany/gaia/commit/7371fe8250245ff8d5fe1c5ae665575eb4910aa8))
* **ci:** the browser stack's scripted wait lasts the second its patience counts ([#1642](https://github.com/theexperiencecompany/gaia/issues/1642)) ([13d0394](https://github.com/theexperiencecompany/gaia/commit/13d0394b225903040139c1b3ee483c4dfd88d724))
* **comms:** one GAIA that reacts instead of replying "on it" and never claims unconfirmed work ([#1669](https://github.com/theexperiencecompany/gaia/issues/1669)) ([254537b](https://github.com/theexperiencecompany/gaia/commit/254537b4982dc1d6b2752516a5a3ba8bfd161407))
* **comms:** production comms back on gpt-5.6-luna ([#1600](https://github.com/theexperiencecompany/gaia/issues/1600)) ([912b6f8](https://github.com/theexperiencecompany/gaia/commit/912b6f8cc334708d6bd48f49f9c945c599433090))
* **comms:** production comms on DeepSeek V4.1 Flash, answers instead of status reports (GAIA-719) ([#1579](https://github.com/theexperiencecompany/gaia/issues/1579)) ([948df27](https://github.com/theexperiencecompany/gaia/commit/948df27e2b2c538301af9c1ca8c8f59f0dbc2be2))
* **conversation:** a background browser run is no longer logged lost by the sweep while it runs ([#1874](https://github.com/theexperiencecompany/gaia/issues/1874)) ([e381277](https://github.com/theexperiencecompany/gaia/commit/e381277ea7176db40a2f684db0844b6ec628e306))
* **conversation:** a background run proves itself alive before its work is logged ([#1875](https://github.com/theexperiencecompany/gaia/issues/1875)) ([a27ce95](https://github.com/theexperiencecompany/gaia/commit/a27ce959f575d6a9d12b5680615fece86b867749))
* **conversation:** workflow fires reach the executor again ([#1872](https://github.com/theexperiencecompany/gaia/issues/1872)) ([63951b7](https://github.com/theexperiencecompany/gaia/commit/63951b7e80adfaf176616ac6cbc8574ad039a487))
* **deps:** bump litellm to 1.103 for GHSA-g5ff-637f-6q2m and CVE-2026-114612 ([1167f77](https://github.com/theexperiencecompany/gaia/commit/1167f7700ecf76468510aa56928a81f40066a6ca))
* **deps:** bump litellm to 1.103 for two security advisories ([#1555](https://github.com/theexperiencecompany/gaia/issues/1555)) ([1167f77](https://github.com/theexperiencecompany/gaia/commit/1167f7700ecf76468510aa56928a81f40066a6ca))
* **deps:** bump Python packages past open Dependabot advisories ([#1628](https://github.com/theexperiencecompany/gaia/issues/1628)) ([73bb7bb](https://github.com/theexperiencecompany/gaia/commit/73bb7bb445b0e648ee8247255f7e4f657f91f258))
* **deps:** wcmatch 11.2 closes CVE-2026-132276 ([#1862](https://github.com/theexperiencecompany/gaia/issues/1862)) ([e6b54c6](https://github.com/theexperiencecompany/gaia/commit/e6b54c64065bdf8e3012ed28c0bbafb20b14563f))
* **device-bridge:** a dropped device socket fails its in-flight calls at once instead of after 120s ([#1924](https://github.com/theexperiencecompany/gaia/issues/1924)) ([e7242a5](https://github.com/theexperiencecompany/gaia/commit/e7242a58a8e72963a7affd532dc953223630c5f7))
* **dev:** resolve mise test:one paths from the directory it was run in ([#1855](https://github.com/theexperiencecompany/gaia/issues/1855)) ([47a7630](https://github.com/theexperiencecompany/gaia/commit/47a7630e9d3dc835a05659f1e60f04c014ddb57c))
* **docker:** ship Fortress only in a separate gaia-fortress image ([#1698](https://github.com/theexperiencecompany/gaia/issues/1698)) ([fecf936](https://github.com/theexperiencecompany/gaia/commit/fecf9368d0afb3063ea17fbc7fc6e0ab46d79ede))
* **executor:** a finished background result is never thrown away; Stop stops the run ([#1586](https://github.com/theexperiencecompany/gaia/issues/1586)) ([0a3a7e2](https://github.com/theexperiencecompany/gaia/commit/0a3a7e2873ddcd7c976b1c4535679667bc3a6e68))
* **executor:** a run whose finish save fails still hands late work to a new run ([#1963](https://github.com/theexperiencecompany/gaia/issues/1963)) ([f3367f9](https://github.com/theexperiencecompany/gaia/commit/f3367f964d3841800fdbc17cd9f4b5e85fe1b379))
* **gmail:** large fetches offload through compaction, not a private Gmail path ([#1635](https://github.com/theexperiencecompany/gaia/issues/1635)) ([013696a](https://github.com/theexperiencecompany/gaia/commit/013696aea6ab0340a3edb2f68492f8da1b8ba127))
* **inbox-desk:** the mail pass finishes on a 7-day inbox and skips a thread Gmail no longer has ([#1670](https://github.com/theexperiencecompany/gaia/issues/1670)) ([090519e](https://github.com/theexperiencecompany/gaia/commit/090519e15b79dd73888d19dd2594fe8478d0190f))
* **integrations:** connect links show what they connect, Dodo re-registers a forgotten client, and the clients use generated API types ([#1972](https://github.com/theexperiencecompany/gaia/issues/1972)) ([4c4f833](https://github.com/theexperiencecompany/gaia/commit/4c4f8331b6763ffecdb43037115dba0f494ea9bb))
* **integrations:** one connect card per run, then calls to that integration are refused ([#1583](https://github.com/theexperiencecompany/gaia/issues/1583)) ([60eb7c7](https://github.com/theexperiencecompany/gaia/commit/60eb7c7684cb5c3f6822885b5cb7a607c1b9a997))
* **integrations:** plain error copy when a connect fails ([#1662](https://github.com/theexperiencecompany/gaia/issues/1662)) ([7213bd1](https://github.com/theexperiencecompany/gaia/commit/7213bd19dc9ae18b79b9e2a17361ede264b6d227))
* **integrations:** standalone auth URLs for OAuth MCP reconnect (GAIA-712) ([#1476](https://github.com/theexperiencecompany/gaia/issues/1476)) ([c1213b5](https://github.com/theexperiencecompany/gaia/commit/c1213b54b49bc0fc5a56c48f3bcbff1185e4fd74))
* **integrations:** stop dialing two Composio servers we do not own ([#1536](https://github.com/theexperiencecompany/gaia/issues/1536)) ([7de1209](https://github.com/theexperiencecompany/gaia/commit/7de12097437ff282f6715b16a3ba05422d6bd72d))
* **llm-stub:** the scripted hand-off sends every argument call_executor requires ([#1679](https://github.com/theexperiencecompany/gaia/issues/1679)) ([af97e7a](https://github.com/theexperiencecompany/gaia/commit/af97e7adbacdb76f59cbd34a6632a00ca023bbef))
* **llm:** a stalled model stream falls back after 45 s instead of hanging to the invoke ceiling ([#1982](https://github.com/theexperiencecompany/gaia/issues/1982)) ([3a3392c](https://github.com/theexperiencecompany/gaia/commit/3a3392c2f52f79efcc9d3a0027498840951e1b3b))
* **llm:** failed model calls log their shape, Workers AI rate limits skip the retries and have an alert ([#1939](https://github.com/theexperiencecompany/gaia/issues/1939)) ([fd77f8c](https://github.com/theexperiencecompany/gaia/commit/fd77f8ca5dd0e32c4e4fc6826dec6dd6ef99c66e))
* **llm:** fall back to the JSON-schema lane when a structured reply is malformed ([#1511](https://github.com/theexperiencecompany/gaia/issues/1511)) ([d3b6f99](https://github.com/theexperiencecompany/gaia/commit/d3b6f99ccbf45203c048c63c29af3608c8934ed3))
* **llm:** provider routing belongs to the model it was chosen for ([#1673](https://github.com/theexperiencecompany/gaia/issues/1673)) ([ea97878](https://github.com/theexperiencecompany/gaia/commit/ea97878319f96bfb9d1719bb7e75d0f7219e4ebe))
* **llm:** retry and fall back on raw transient httpx errors ([#1495](https://github.com/theexperiencecompany/gaia/issues/1495)) ([85936f5](https://github.com/theexperiencecompany/gaia/commit/85936f572d9f1a889e96d3cc9c01d93bf3e08692))
* **llm:** Workers AI's quirks live in its adapter, and a failed one-shot goes to another provider ([#1923](https://github.com/theexperiencecompany/gaia/issues/1923)) ([8f84198](https://github.com/theexperiencecompany/gaia/commit/8f84198a6d863db273cf8dfa975e5105713ee993))
* **mcp:** OAuth and bearer tokens only travel to MCP servers over https, or plain http on the local network ([#1998](https://github.com/theexperiencecompany/gaia/issues/1998)) ([e77abb2](https://github.com/theexperiencecompany/gaia/commit/e77abb2f6847769e2765abac54c64f52813ea8f4))
* **mcp:** OAuth MCP integrations keep working past token expiry (metadata-document refresh, live-session refresh) ([#1976](https://github.com/theexperiencecompany/gaia/issues/1976)) ([2706341](https://github.com/theexperiencecompany/gaia/commit/2706341c2df64e3c1e68e0c096100dc26ba15e56))
* **memory:** let recall report its handled embedding failures ([#1497](https://github.com/theexperiencecompany/gaia/issues/1497)) ([ddf468f](https://github.com/theexperiencecompany/gaia/commit/ddf468f28d482a9e746b10681bd8c728b383ba87))
* **migration:** the catch-up drops messages the old build trimmed off a migrated array ([#1871](https://github.com/theexperiencecompany/gaia/issues/1871)) ([aefd68b](https://github.com/theexperiencecompany/gaia/commit/aefd68b8bd4ffdb132365c9a63ccf06e0299de76))
* **observability:** keep trace-export failures visible instead of muting the logger ([#1510](https://github.com/theexperiencecompany/gaia/issues/1510)) ([0c9f065](https://github.com/theexperiencecompany/gaia/commit/0c9f065ad559a8c06c7d802a66838365fedbf810))
* **onboarding:** one server event per wizard step, retrying answers save, wait for the bot link, log out ([#1591](https://github.com/theexperiencecompany/gaia/issues/1591)) ([735f860](https://github.com/theexperiencecompany/gaia/commit/735f8606c2cdfcabf67d2ee4470bc7f131d6c23a))
* **payments:** accept the payment fields Dodo sends as null ([#1488](https://github.com/theexperiencecompany/gaia/issues/1488)) ([685b784](https://github.com/theexperiencecompany/gaia/commit/685b78455b0a94489e85e607d457ea3a74bf07a8))
* **payments:** let a stuck webhook claim expire before the retries do ([#1542](https://github.com/theexperiencecompany/gaia/issues/1542)) ([32fc77f](https://github.com/theexperiencecompany/gaia/commit/32fc77fea5d2b55824a5ed3075fa80d24c17992c))
* **playbook:** a UTC timestamp ending in Z is the ISO layout; time_layout is an author-choice refusal ([#1675](https://github.com/theexperiencecompany/gaia/issues/1675)) ([9fe548d](https://github.com/theexperiencecompany/gaia/commit/9fe548d0a808385084d547e6b5d51e43d8b92060))
* **sandbox:** treat bash command timeouts as an expected outcome ([#1487](https://github.com/theexperiencecompany/gaia/issues/1487)) ([0b6ea26](https://github.com/theexperiencecompany/gaia/commit/0b6ea26666c0a01969dc227b525dd4d1fbeb2315))
* **scripts:** every API script boots through boot_process, enforced by a meta test ([#1995](https://github.com/theexperiencecompany/gaia/issues/1995)) ([4e29884](https://github.com/theexperiencecompany/gaia/commit/4e29884cf6c7bfd040f41842c367a805289d449d))
* **scripts:** the Inbox desk backfill boots the app and binds an analytics context, so it can run at all ([4080a5e](https://github.com/theexperiencecompany/gaia/commit/4080a5eadf800e078a8d374639c58122e8dad8ff))
* **scripts:** the Inbox desk backfill boots the app, so it can run at all ([#1988](https://github.com/theexperiencecompany/gaia/issues/1988)) ([4080a5e](https://github.com/theexperiencecompany/gaia/commit/4080a5eadf800e078a8d374639c58122e8dad8ff))
* **sentry:** attribute the wide event's user and group messages by their shape ([#1509](https://github.com/theexperiencecompany/gaia/issues/1509)) ([b0c311b](https://github.com/theexperiencecompany/gaia/commit/b0c311bac51f8fa89a72d3eb90ea35146fa3b1d2))
* **sentry:** stop forwarding mcp_use's own error lines to Sentry ([#1496](https://github.com/theexperiencecompany/gaia/issues/1496)) ([0e952fd](https://github.com/theexperiencecompany/gaia/commit/0e952fdb75b3335cda9648b05450715d63b7118c))
* **seo:** live-crawl findings after [#1797](https://github.com/theexperiencecompany/gaia/issues/1797), and no session-only calls for signed-out visitors ([#1822](https://github.com/theexperiencecompany/gaia/issues/1822)) ([494728e](https://github.com/theexperiencecompany/gaia/commit/494728e7373af05feac2c26e19003203b4ed4bdb))
* **seo:** real fixes for the squirrelscan Links, URL, Content, Images and title findings ([#1702](https://github.com/theexperiencecompany/gaia/issues/1702)) ([1d90922](https://github.com/theexperiencecompany/gaia/commit/1d90922d2f6bccb282875a82569f17b20b034ec4))
* **todos:** a todo run takes a chat whose executor died, and a cancelled todo job stops its run ([#1964](https://github.com/theexperiencecompany/gaia/issues/1964)) ([1555da8](https://github.com/theexperiencecompany/gaia/commit/1555da861db6d775bf64c9f5c7d1a230dfceb296))
* **tooling:** fresh-worktree hooks and ci:local name the install command instead of crashing ([#1823](https://github.com/theexperiencecompany/gaia/issues/1823)) ([0b06f8e](https://github.com/theexperiencecompany/gaia/commit/0b06f8e5035047871087702843c7c24533daead8))
* **triggers:** calendar "N minutes before" triggers fire N minutes before, not at Composio's 10-minute default ([#1984](https://github.com/theexperiencecompany/gaia/issues/1984)) ([9011b87](https://github.com/theexperiencecompany/gaia/commit/9011b87083f9e9d77d62d69481ec1740e926235a))
* **triggers:** calendar triggers use the pinned Composio field names, and the re-registration script boots and fails loud ([#1994](https://github.com/theexperiencecompany/gaia/issues/1994)) ([d0b32dc](https://github.com/theexperiencecompany/gaia/commit/d0b32dcb3817e4f3b771abc595871c55fc667cbe))
* usage stops at 100% of the monthly allowance with a clear reset date; visible attachment limits ([#1582](https://github.com/theexperiencecompany/gaia/issues/1582)) ([fcfa685](https://github.com/theexperiencecompany/gaia/commit/fcfa6850cafff3a21fa27d7148b57bcde0f85618))
* **usage:** budget-wall cards name the wall that bound, and bots relay its message ([#1663](https://github.com/theexperiencecompany/gaia/issues/1663)) ([f97cea1](https://github.com/theexperiencecompany/gaia/commit/f97cea101c56c03adb9ec265dffbc6938f9007f3))
* **voice:** route each room to its own environment's agent and speak backend errors ([#1769](https://github.com/theexperiencecompany/gaia/issues/1769)) ([343526b](https://github.com/theexperiencecompany/gaia/commit/343526b99a9342273a40d9203d0ff0371bf1f64e))
* **web:** rebuild public pages the moment a published integration or workflow changes ([#1937](https://github.com/theexperiencecompany/gaia/issues/1937)) ([0d88b89](https://github.com/theexperiencecompany/gaia/commit/0d88b89feec14b2c66a9321da614ce353e004dc4))
* **web:** unpaid accounts never touch the paid app shell ([#1585](https://github.com/theexperiencecompany/gaia/issues/1585)) ([34c1b73](https://github.com/theexperiencecompany/gaia/commit/34c1b73e6371f519d164a719f9d5892c628d5c87))
* **workflows:** draft steps without reasoning, behind one retry layer ([#1604](https://github.com/theexperiencecompany/gaia/issues/1604)) ([890a6b8](https://github.com/theexperiencecompany/gaia/commit/890a6b86cbfae62b5e7c9d7b48f1f6496fd6aaa7))
* **workflows:** resolve the Gmail fetch session from the replay's conversation_id ([#1494](https://github.com/theexperiencecompany/gaia/issues/1494)) ([ad0d919](https://github.com/theexperiencecompany/gaia/commit/ad0d919d730227b2862b8e0188a3dad64d8009b5))
* **workflows:** scheduled runs are counted, playbook times take seconds, and alert email is opt-in ([#1930](https://github.com/theexperiencecompany/gaia/issues/1930)) ([c37b4e1](https://github.com/theexperiencecompany/gaia/commit/c37b4e1b7edcce655e934b961316f99617efa6d9))


### Performance Improvements

* **api:** a tracked todo run recalls memories on its title, not its 8-20k-char brief ([#1983](https://github.com/theexperiencecompany/gaia/issues/1983)) ([b52c6a6](https://github.com/theexperiencecompany/gaia/commit/b52c6a6acda93d6140d12b717e4afdab4e5af337))
* **api:** an events stream open reads only the log window it sends, and a resume after a reaction sends only the amended item ([#1993](https://github.com/theexperiencecompany/gaia/issues/1993)) ([09d6b46](https://github.com/theexperiencecompany/gaia/commit/09d6b466263e2c0d729f9fe735498271a851d01f))
* **api:** faster, measured chat turns  memory lane fix, cached WorkOS keys, per-step timing ([#1840](https://github.com/theexperiencecompany/gaia/issues/1840)) ([ead06e0](https://github.com/theexperiencecompany/gaia/commit/ead06e0517228c141ca941ab60fe8981fad9c927))
* **api:** move VFS marker IO and journal dedupe off the event loop ([#1859](https://github.com/theexperiencecompany/gaia/issues/1859)) ([65747bb](https://github.com/theexperiencecompany/gaia/commit/65747bbe0763dcaabc94deb2cff315d4c6aec18d))
* **ci:** deploy the commit the merge queue tested, and start 12 jobs per PR push instead of 18 ([#1863](https://github.com/theexperiencecompany/gaia/issues/1863)) ([04d040b](https://github.com/theexperiencecompany/gaia/commit/04d040b869f8365d78f66af2fb811ad345151342))
* **ci:** mutation skips scripts, migrations, prompt text and constants-only modules ([#1903](https://github.com/theexperiencecompany/gaia/issues/1903)) ([98cd5b8](https://github.com/theexperiencecompany/gaia/commit/98cd5b836f0e67b32a4d6e571836428a15e3d7c1))
* **conversation:** the events stream sends each card once, changes as patches, and resumes after a head ([#1945](https://github.com/theexperiencecompany/gaia/issues/1945)) ([d85016a](https://github.com/theexperiencecompany/gaia/commit/d85016a7deaa23ad70eaca7276a02398d03d0dff))
* cut our latency around the comms model call on web and bots ([#1831](https://github.com/theexperiencecompany/gaia/issues/1831)) ([837d31b](https://github.com/theexperiencecompany/gaia/commit/837d31b994c23dc5c3566ac906f88aa3b35e3e67))
</details>

<details><summary>web: 0.27.0</summary>

## [0.27.0](https://github.com/theexperiencecompany/gaia/compare/web-v0.26.0...web-v0.27.0) (2026-11-28)


### Features

* **api:** resume a chat, todo or workflow once the user connects or configures what it asked for ([#1779](https://github.com/theexperiencecompany/gaia/issues/1779)) ([e99a935](https://github.com/theexperiencecompany/gaia/commit/e99a935b339fd666c409883d9093ac413b6fd8d2))
* **briefing:** daily and weekly briefs, heygaia.link sharing, and OpenUI artifacts ([#1853](https://github.com/theexperiencecompany/gaia/issues/1853)) ([b0c7d7c](https://github.com/theexperiencecompany/gaia/commit/b0c7d7c38edec5d4d4e7a1b497b792efe5b925ec))
* **ci:** nx decides what CI runs; stop the self-made flakes and silent passes ([#1569](https://github.com/theexperiencecompany/gaia/issues/1569)) ([c722c9c](https://github.com/theexperiencecompany/gaia/commit/c722c9c021df2a050773dfe34cb2d9040bed2aeb))
* **conversation:** the conversation-runtime redesign (stack [#1716](https://github.com/theexperiencecompany/gaia/issues/1716)[#1723](https://github.com/theexperiencecompany/gaia/issues/1723), landed as one) ([#1723](https://github.com/theexperiencecompany/gaia/issues/1723)) ([8ff2293](https://github.com/theexperiencecompany/gaia/commit/8ff2293d14eb97e6fba582ba1b1fdb9dc3a99730))
* **delivery:** presence-aware, one-place proactive messaging ([#1523](https://github.com/theexperiencecompany/gaia/issues/1523)) ([39887cf](https://github.com/theexperiencecompany/gaia/commit/39887cfe9e9fe0b6c7a1fe5daa916cf09eac2b2f))
* **inbox:** JEV buckets the desk's mail into reply, waiting, act, fyi and junk; gate skips stay bounded ([#1667](https://github.com/theexperiencecompany/gaia/issues/1667)) ([29f0697](https://github.com/theexperiencecompany/gaia/commit/29f0697a512c1d0fcd8037c49e2795f21073bbe3))
* **observability:** every alert rule reaches prod, every user-facing failure has a signal, and alerts name what broke ([#1911](https://github.com/theexperiencecompany/gaia/issues/1911)) ([e8ea875](https://github.com/theexperiencecompany/gaia/commit/e8ea8752ea7eda08d6a0d36681ebf7fb41553e32))
* **onboarding:** ask where the user heard about GAIA ([#1967](https://github.com/theexperiencecompany/gaia/issues/1967)) ([197f123](https://github.com/theexperiencecompany/gaia/commit/197f123ee928733f96d947979a43bd7066749f02))
* **onboarding:** first conversations users can trust, in their language ([#1584](https://github.com/theexperiencecompany/gaia/issues/1584)) ([9326f82](https://github.com/theexperiencecompany/gaia/commit/9326f82aaf40dfd220c99d8fb7d9a1ff6ea0b241))
* **settings:** open a linked Telegram, WhatsApp or iMessage chat from linked accounts ([#1633](https://github.com/theexperiencecompany/gaia/issues/1633)) ([b6eb365](https://github.com/theexperiencecompany/gaia/commit/b6eb36542021563f8dfbaa855b9763f0ce4f955e))
* **settings:** quiet hours are the user's own, set on a noon-to-noon slider ([#1664](https://github.com/theexperiencecompany/gaia/issues/1664)) ([074b108](https://github.com/theexperiencecompany/gaia/commit/074b1089d6e92d0b64988fbcdbf4b53f13db9939))
* **todos:** give every tracked todo its own chat, led by what woke each run ([#1561](https://github.com/theexperiencecompany/gaia/issues/1561)) ([7fa8464](https://github.com/theexperiencecompany/gaia/commit/7fa84648be37066f58b4929dc0f8a0c468d8f1f9))
* **web:** an unpaid account stays in the app behind the upgrade wall, which links to the plans ([#1941](https://github.com/theexperiencecompany/gaia/issues/1941)) ([0839de7](https://github.com/theexperiencecompany/gaia/commit/0839de742431f7fc203fb93fb914e3dd245d71fe))
* **web:** Briefings settings shows and sets the one chat app briefs go to ([#1956](https://github.com/theexperiencecompany/gaia/issues/1956)) ([f2a8fad](https://github.com/theexperiencecompany/gaia/commit/f2a8fad1aa483ff61bb6f910ae1f2d5a5a337f3f))
* **web:** chat day dividers and a notifications panel layout pass ([#1953](https://github.com/theexperiencecompany/gaia/issues/1953)) ([7862f06](https://github.com/theexperiencecompany/gaia/commit/7862f06c8f58322b7c372bf03f25a1d4ad8b8ac7))
* **web:** migrate HeroUI v2 ’ v3 (perf 77’100) ([#1577](https://github.com/theexperiencecompany/gaia/issues/1577)) ([61acd9c](https://github.com/theexperiencecompany/gaia/commit/61acd9c8b6cfacbebb5d161714756addd1dbe991))
* **web:** nonce-based Content-Security-Policy at the edge, report-only first ([#1764](https://github.com/theexperiencecompany/gaia/issues/1764)) ([297ab43](https://github.com/theexperiencecompany/gaia/commit/297ab43a046ff47dc5fbc2930a4c97d46933d469))
* **web:** see, edit and turn off a job's Runs only when rule ([#1661](https://github.com/theexperiencecompany/gaia/issues/1661)) ([e89213c](https://github.com/theexperiencecompany/gaia/commit/e89213c039dfe86ae238d1d0bdf0cbc8b896243a))
* **web:** the visible fixes from the heygaia.io audit ([#1539](https://github.com/theexperiencecompany/gaia/issues/1539)) ([fc67d3d](https://github.com/theexperiencecompany/gaia/commit/fc67d3d8301634b4cd807ab6e3a5ee8c18861bc1))
* **workflows:** GAIA writes a job's Runs only when condition as it creates it ([#1660](https://github.com/theexperiencecompany/gaia/issues/1660)) ([6beec4d](https://github.com/theexperiencecompany/gaia/commit/6beec4d9752b9c504d20bd6eb68907f8cc180343))


### Bug Fixes

* **api:** a tool card keeps at most the output the model is given, and says when it was cut ([#1954](https://github.com/theexperiencecompany/gaia/issues/1954)) ([5d4073a](https://github.com/theexperiencecompany/gaia/commit/5d4073ad2d5f2189fbe5b1aec400d4b38d0f146d))
* **bots:** point every bot link at one set of handles ([#1672](https://github.com/theexperiencecompany/gaia/issues/1672)) ([68858b3](https://github.com/theexperiencecompany/gaia/commit/68858b3cc47eacf4552a860e09050958500231e1))
* **browser:** serve the live view under /api/v1 so its socket upgrades behind every proxy ([#1578](https://github.com/theexperiencecompany/gaia/issues/1578)) ([35625ca](https://github.com/theexperiencecompany/gaia/commit/35625ca019f70c057165ac0a95d2c26780bacba8))
* **chat:** bot DM chats stay cached and sync incrementally instead of reloading in full ([#1691](https://github.com/theexperiencecompany/gaia/issues/1691)) ([3f85a3f](https://github.com/theexperiencecompany/gaia/commit/3f85a3f40c898a8319641af3f6225dca87eee365))
* **checkout:** keep the Dodo overlay in the app and never strand a payer ([#1587](https://github.com/theexperiencecompany/gaia/issues/1587)) ([ae8550b](https://github.com/theexperiencecompany/gaia/commit/ae8550bc4f5da7ae743ae24e6baac4ab06e89bbc))
* **ci:** a dispatched run off master builds the web bundle as a check ([#1844](https://github.com/theexperiencecompany/gaia/issues/1844)) ([62756e3](https://github.com/theexperiencecompany/gaia/commit/62756e38329b1ea54701b62b31ceecc0517331a1))
* **ci:** commit hooks install node_modules once in a fresh worktree ([#1818](https://github.com/theexperiencecompany/gaia/issues/1818)) ([fba3a25](https://github.com/theexperiencecompany/gaia/commit/fba3a2569a9806a2bfb5d82aa4f9fa46d9dd923f))
* **ci:** every web build presents INTERNAL_API_TOKEN, and a tokenless build waits out a 429 ([#1895](https://github.com/theexperiencecompany/gaia/issues/1895)) ([a5b5e86](https://github.com/theexperiencecompany/gaia/commit/a5b5e86f8470996e3e2435bef2f00907fbfe157f))
* **ci:** stop six tooling traps agents hit landing a stacked PR ([#1730](https://github.com/theexperiencecompany/gaia/issues/1730)) ([7371fe8](https://github.com/theexperiencecompany/gaia/commit/7371fe8250245ff8d5fe1c5ae665575eb4910aa8))
* **comms:** one GAIA that reacts instead of replying "on it" and never claims unconfirmed work ([#1669](https://github.com/theexperiencecompany/gaia/issues/1669)) ([254537b](https://github.com/theexperiencecompany/gaia/commit/254537b4982dc1d6b2752516a5a3ba8bfd161407))
* **deps:** close the open npm Dependabot alerts ([#1630](https://github.com/theexperiencecompany/gaia/issues/1630)) ([7b2c8cd](https://github.com/theexperiencecompany/gaia/commit/7b2c8cdfb6e9b7553ea0d025a139368a46a30b53))
* **dev:** a worktree's web dev server reads its own apps/web/.env ([#1821](https://github.com/theexperiencecompany/gaia/issues/1821)) ([fd6f261](https://github.com/theexperiencecompany/gaia/commit/fd6f2616f6278a03e17cf746fb14e7f7022e85ed))
* **dev:** the web dev server targets this worktree's API port ([#1598](https://github.com/theexperiencecompany/gaia/issues/1598)) ([c40d623](https://github.com/theexperiencecompany/gaia/commit/c40d6231b5bc843c01540619f54ec186bce7f5b7))
* **e2e:** the screen tests serve remote optimized images locally ([#1949](https://github.com/theexperiencecompany/gaia/issues/1949)) ([16298c7](https://github.com/theexperiencecompany/gaia/commit/16298c78db012ade504755b03a9900f995ed227c))
* **executor:** a finished background result is never thrown away; Stop stops the run ([#1586](https://github.com/theexperiencecompany/gaia/issues/1586)) ([0a3a7e2](https://github.com/theexperiencecompany/gaia/commit/0a3a7e2873ddcd7c976b1c4535679667bc3a6e68))
* **integrations:** connect links show what they connect, Dodo re-registers a forgotten client, and the clients use generated API types ([#1972](https://github.com/theexperiencecompany/gaia/issues/1972)) ([4c4f833](https://github.com/theexperiencecompany/gaia/commit/4c4f8331b6763ffecdb43037115dba0f494ea9bb))
* **integrations:** one connect card per run, then calls to that integration are refused ([#1583](https://github.com/theexperiencecompany/gaia/issues/1583)) ([60eb7c7](https://github.com/theexperiencecompany/gaia/commit/60eb7c7684cb5c3f6822885b5cb7a607c1b9a997))
* **integrations:** plain error copy when a connect fails ([#1662](https://github.com/theexperiencecompany/gaia/issues/1662)) ([7213bd1](https://github.com/theexperiencecompany/gaia/commit/7213bd19dc9ae18b79b9e2a17361ede264b6d227))
* **llm:** a stalled model stream falls back after 45 s instead of hanging to the invoke ceiling ([#1982](https://github.com/theexperiencecompany/gaia/issues/1982)) ([3a3392c](https://github.com/theexperiencecompany/gaia/commit/3a3392c2f52f79efcc9d3a0027498840951e1b3b))
* **onboarding:** one server event per wizard step, retrying answers save, wait for the bot link, log out ([#1591](https://github.com/theexperiencecompany/gaia/issues/1591)) ([735f860](https://github.com/theexperiencecompany/gaia/commit/735f8606c2cdfcabf67d2ee4470bc7f131d6c23a))
* **seo:** Core SEO and Links: meta descriptions in window, indexable /signup, /manifesto folded into /about ([#1763](https://github.com/theexperiencecompany/gaia/issues/1763)) ([4fa4407](https://github.com/theexperiencecompany/gaia/commit/4fa440723ad379b8cd5ff74db39227356f39bcf4))
* **seo:** every page description fits the snippet window, and the audit fails on warnings ([#1531](https://github.com/theexperiencecompany/gaia/issues/1531)) ([167d58c](https://github.com/theexperiencecompany/gaia/commit/167d58ca73ae927155e0c4abd5bc5159c3a45963))
* **seo:** full-crawl Links and URL Structure to 100, family pages ship half the CSS ([#1797](https://github.com/theexperiencecompany/gaia/issues/1797)) ([dad3377](https://github.com/theexperiencecompany/gaia/commit/dad3377db52ed03387c354463b07094c22c7f935))
* **seo:** give hub children, categories and paginated hubs a contextual inbound link ([#1740](https://github.com/theexperiencecompany/gaia/issues/1740)) ([f590a9e](https://github.com/theexperiencecompany/gaia/commit/f590a9e27629e5af50c197bcbe7e7a2efe9ab3da))
* **seo:** live-crawl findings after [#1797](https://github.com/theexperiencecompany/gaia/issues/1797), and no session-only calls for signed-out visitors ([#1822](https://github.com/theexperiencecompany/gaia/issues/1822)) ([494728e](https://github.com/theexperiencecompany/gaia/commit/494728e7373af05feac2c26e19003203b4ed4bdb))
* **seo:** paginated hubs self-canonicalise with their own titles, /features caching, app-route and dev-host leaks ([#1719](https://github.com/theexperiencecompany/gaia/issues/1719)) ([5a32a3b](https://github.com/theexperiencecompany/gaia/commit/5a32a3b22a4cf338921a67ef5f75c6021d8b0fc4))
* **seo:** real fixes for the squirrelscan Links, URL, Content, Images and title findings ([#1702](https://github.com/theexperiencecompany/gaia/issues/1702)) ([1d90922](https://github.com/theexperiencecompany/gaia/commit/1d90922d2f6bccb282875a82569f17b20b034ec4))
* **seo:** retry dropped connections in the post-deploy audit, regenerate the live squirrel baseline ([#1828](https://github.com/theexperiencecompany/gaia/issues/1828)) ([0d638b6](https://github.com/theexperiencecompany/gaia/commit/0d638b677721137a398b770741c65052b5a44488))
* **seo:** what an independent squirrelscan audit of heygaia.io found ([#1535](https://github.com/theexperiencecompany/gaia/issues/1535)) ([3724461](https://github.com/theexperiencecompany/gaia/commit/3724461e118da4b8a91b18a3260ff914c4c18763))
* usage stops at 100% of the monthly allowance with a clear reset date; visible attachment limits ([#1582](https://github.com/theexperiencecompany/gaia/issues/1582)) ([fcfa685](https://github.com/theexperiencecompany/gaia/commit/fcfa6850cafff3a21fa27d7148b57bcde0f85618))
* **usage:** budget-wall cards name the wall that bound, and bots relay its message ([#1663](https://github.com/theexperiencecompany/gaia/issues/1663)) ([f97cea1](https://github.com/theexperiencecompany/gaia/commit/f97cea101c56c03adb9ec265dffbc6938f9007f3))
* **voice:** route each room to its own environment's agent and speak backend errors ([#1769](https://github.com/theexperiencecompany/gaia/issues/1769)) ([343526b](https://github.com/theexperiencecompany/gaia/commit/343526b99a9342273a40d9203d0ff0371bf1f64e))
* **web:** /contact form looped on re-render (React [#301](https://github.com/theexperiencecompany/gaia/issues/301)) ([#1537](https://github.com/theexperiencecompany/gaia/issues/1537)) ([5ffe91b](https://github.com/theexperiencecompany/gaia/commit/5ffe91b9811a91498ca06c3cc6711bcd832cbd90))
* **web:** /settings answers a real 307 instead of a meta-refresh reload ([#1796](https://github.com/theexperiencecompany/gaia/issues/1796)) ([408ec81](https://github.com/theexperiencecompany/gaia/commit/408ec8132136ad234262ac119a2c6124d142a343))
* **web:** /thanks loads tool favicons from the favicon service, never from the tool's own site ([#1921](https://github.com/theexperiencecompany/gaia/issues/1921)) ([95f558b](https://github.com/theexperiencecompany/gaia/commit/95f558b58b453c527d11980fa02dfa60bd6c6f67))
* **web:** a todo's coloured chips take their text colour from their chip colour ([#1666](https://github.com/theexperiencecompany/gaia/issues/1666)) ([bcddbf5](https://github.com/theexperiencecompany/gaia/commit/bcddbf59c31b5005160376e677f0123468ff6c10))
* **web:** clear squirrel's crawl, image, social and schema leftovers at their source ([#1739](https://github.com/theexperiencecompany/gaia/issues/1739)) ([f345259](https://github.com/theexperiencecompany/gaia/commit/f3452595f452fee13bcf5145c373f093f12691af))
* **web:** clear the easy squirrel a11y and content findings ([#1640](https://github.com/theexperiencecompany/gaia/issues/1640)) ([376f65c](https://github.com/theexperiencecompany/gaia/commit/376f65c04e69d0fe61436aba2d2195fd4ce708b3))
* **web:** direct CDN URLs for author avatars (Ahrefs broken images) ([#1575](https://github.com/theexperiencecompany/gaia/issues/1575)) ([f626977](https://github.com/theexperiencecompany/gaia/commit/f626977743220d193b7d6912cbaa4e7c69c66a5e))
* **web:** HttpOnly locale cookie (Security 96) ([#1559](https://github.com/theexperiencecompany/gaia/issues/1559)) ([b23ac96](https://github.com/theexperiencecompany/gaia/commit/b23ac96efc66ba07e6b37208c8bdafd6b48d72ce))
* **web:** landing hubs open with a short line instead of a paragraph wall ([#1701](https://github.com/theexperiencecompany/gaia/issues/1701)) ([40c2c4b](https://github.com/theexperiencecompany/gaia/commit/40c2c4bf1d43b10f52a6fc8b484f0f530ddebaaa))
* **web:** lowercase the pt-BR locale segment (URL Structure 100) ([#1574](https://github.com/theexperiencecompany/gaia/issues/1574)) ([e19c069](https://github.com/theexperiencecompany/gaia/commit/e19c069851636d84bca68ccf0a1448ae3749e6e7))
* **web:** notifications get a header check button, the app's pill tabs, and titles that truncate ([#1959](https://github.com/theexperiencecompany/gaia/issues/1959)) ([68728e5](https://github.com/theexperiencecompany/gaia/commit/68728e5df3c1e8a1206743e490cd84e9991d3947))
* **web:** one owner removes the deployed source maps; the landing check runs on every build ([#1614](https://github.com/theexperiencecompany/gaia/issues/1614)) ([118c5b8](https://github.com/theexperiencecompany/gaia/commit/118c5b8b367e35f700ca1f1a68accd125376e99b))
* **web:** pricing page fails the render when the plan fetch fails ([#1908](https://github.com/theexperiencecompany/gaia/issues/1908)) ([987a99e](https://github.com/theexperiencecompany/gaia/commit/987a99e18395afcf008744687aba568532b41b4a))
* **web:** rebuild public pages the moment a published integration or workflow changes ([#1937](https://github.com/theexperiencecompany/gaia/issues/1937)) ([0d88b89](https://github.com/theexperiencecompany/gaia/commit/0d88b89feec14b2c66a9321da614ce353e004dc4))
* **web:** recover stale-deploy module errors behind the route error boundary ([#1485](https://github.com/theexperiencecompany/gaia/issues/1485)) ([2b2eb98](https://github.com/theexperiencecompany/gaia/commit/2b2eb984e644ce220e7232faf07f0808cbdca397))
* **web:** repair the chat composer, workflow card widths, and settings flyouts ([#1857](https://github.com/theexperiencecompany/gaia/issues/1857)) ([571ff7b](https://github.com/theexperiencecompany/gaia/commit/571ff7bb5a40bd8716b82b6f6835e27e18fb173d))
* **web:** restore /feed and stop serving source maps ([#1563](https://github.com/theexperiencecompany/gaia/issues/1563)) ([7243781](https://github.com/theexperiencecompany/gaia/commit/72437810b971d29c76730a9741f1286fda8351a2))
* **web:** restore v2 chip styling after the HeroUI v3 upgrade ([#1989](https://github.com/theexperiencecompany/gaia/issues/1989)) ([2209c49](https://github.com/theexperiencecompany/gaia/commit/2209c49f584d6eb63aa2e1048de1dc2bae0de030))
* **web:** retry server API reads during the build instead of failing on a slow response ([#1648](https://github.com/theexperiencecompany/gaia/issues/1648)) ([1539b0e](https://github.com/theexperiencecompany/gaia/commit/1539b0e4e26129771ecb80cf21c4b413d2e57735))
* **web:** scan tracked files with one git grep in the public-images test ([#1643](https://github.com/theexperiencecompany/gaia/issues/1643)) ([43e0e5e](https://github.com/theexperiencecompany/gaia/commit/43e0e5e235d939d59e6c81304a982361a9072fc0))
* **web:** the 404 page is styled again, and a rendered class with no CSS fails the worker smoke ([#1936](https://github.com/theexperiencecompany/gaia/issues/1936)) ([0c06ef6](https://github.com/theexperiencecompany/gaia/commit/0c06ef66568f37241b0ef55393d050bb249c276a))
* **web:** the build fetches marketplace data once and retries, instead of once per page ([#1760](https://github.com/theexperiencecompany/gaia/issues/1760)) ([5ebb45b](https://github.com/theexperiencecompany/gaia/commit/5ebb45b0e189ceb21bbad6dd1a40e6dbde428c2e))
* **web:** the build retries a 502/503/504 from the API gateway instead of failing on the first one ([#1910](https://github.com/theexperiencecompany/gaia/issues/1910)) ([ee09275](https://github.com/theexperiencecompany/gaia/commit/ee092756b7429e8420746f3e067995b38e8cdfb3))
* **web:** unpaid accounts never touch the paid app shell ([#1585](https://github.com/theexperiencecompany/gaia/issues/1585)) ([34c1b73](https://github.com/theexperiencecompany/gaia/commit/34c1b73e6371f519d164a719f9d5892c628d5c87))


### Performance Improvements

* **ci:** deploy the commit the merge queue tested, and start 12 jobs per PR push instead of 18 ([#1863](https://github.com/theexperiencecompany/gaia/issues/1863)) ([04d040b](https://github.com/theexperiencecompany/gaia/commit/04d040b869f8365d78f66af2fb811ad345151342))
* **ci:** web e2e and bot scenarios run in two shards each instead of one 33-minute job ([#1877](https://github.com/theexperiencecompany/gaia/issues/1877)) ([6c5ef98](https://github.com/theexperiencecompany/gaia/commit/6c5ef988fbf187ab671c53f16d1eac1bb248dcc6))
* **conversation:** the events stream sends each card once, changes as patches, and resumes after a head ([#1945](https://github.com/theexperiencecompany/gaia/issues/1945)) ([d85016a](https://github.com/theexperiencecompany/gaia/commit/d85016a7deaa23ad70eaca7276a02398d03d0dff))
* **web:** a third less JavaScript on phones (marketing 46’59 on home), no visible change ([#1766](https://github.com/theexperiencecompany/gaia/issues/1766)) ([890996d](https://github.com/theexperiencecompany/gaia/commit/890996df5c601edea66ee3094882d08addbd2262))
* **web:** drop the 1920w phone_dock variant (last oversized image) ([#1576](https://github.com/theexperiencecompany/gaia/issues/1576)) ([f888784](https://github.com/theexperiencecompany/gaia/commit/f888784d02e43ecae8d5e2fb14bfb2eed3c98e00))
* **web:** fixed-width phone_dock so the 1920w variant cannot exist ([f888784](https://github.com/theexperiencecompany/gaia/commit/f888784d02e43ecae8d5e2fb14bfb2eed3c98e00))
* **web:** marketing pages stop loading the chat stack, PostHog SDK and OpenUI CSS ([#1540](https://github.com/theexperiencecompany/gaia/issues/1540)) ([63d885e](https://github.com/theexperiencecompany/gaia/commit/63d885e35fd2e27773213c4a2337097f75a91063))
* **web:** max-age + Last-Modified for the ISR hub pages ([#1571](https://github.com/theexperiencecompany/gaia/issues/1571)) ([91b3ad9](https://github.com/theexperiencecompany/gaia/commit/91b3ad9eb92f2aefdf029f5baf8d5458710b29d3))
* **web:** phone_dock at display width, fewer duplicate image loads ([#1570](https://github.com/theexperiencecompany/gaia/issues/1570)) ([bfc8c70](https://github.com/theexperiencecompany/gaia/commit/bfc8c70bd00c25f944948eeb5f75488596603a5c))
* **web:** request phone_dock at its display width, stop double-loading it ([bfc8c70](https://github.com/theexperiencecompany/gaia/commit/bfc8c70bd00c25f944948eeb5f75488596603a5c))
* **web:** strip source-map comments, extend hub caching, cap phone_dock ([#1573](https://github.com/theexperiencecompany/gaia/issues/1573)) ([07fe512](https://github.com/theexperiencecompany/gaia/commit/07fe51202069c0d77d295340cbf8162ca65a2380))
* **web:** the signed-in app mounts without waiting for the plan read ([#1935](https://github.com/theexperiencecompany/gaia/issues/1935)) ([71d5726](https://github.com/theexperiencecompany/gaia/commit/71d5726176c6f44de7195abd22ed3129e9ea08ca))
</details>

<details><summary>desktop: 0.9.0</summary>

## [0.9.0](https://github.com/theexperiencecompany/gaia/compare/desktop-v0.8.0...desktop-v0.9.0) (2026-11-28)


### Features

* **conversation:** the conversation-runtime redesign (stack [#1716](https://github.com/theexperiencecompany/gaia/issues/1716)[#1723](https://github.com/theexperiencecompany/gaia/issues/1723), landed as one) ([#1723](https://github.com/theexperiencecompany/gaia/issues/1723)) ([8ff2293](https://github.com/theexperiencecompany/gaia/commit/8ff2293d14eb97e6fba582ba1b1fdb9dc3a99730))


### Bug Fixes

* **deps:** close the open npm Dependabot alerts ([#1630](https://github.com/theexperiencecompany/gaia/issues/1630)) ([7b2c8cd](https://github.com/theexperiencecompany/gaia/commit/7b2c8cdfb6e9b7553ea0d025a139368a46a30b53))
</details>

<details><summary>mobile: 0.10.0</summary>

## [0.10.0](https://github.com/theexperiencecompany/gaia/compare/mobile-v0.9.0...mobile-v0.10.0) (2026-11-28)


### Features

* **briefing:** daily and weekly briefs, heygaia.link sharing, and OpenUI artifacts ([#1853](https://github.com/theexperiencecompany/gaia/issues/1853)) ([b0c7d7c](https://github.com/theexperiencecompany/gaia/commit/b0c7d7c38edec5d4d4e7a1b497b792efe5b925ec))
* **conversation:** the conversation-runtime redesign (stack [#1716](https://github.com/theexperiencecompany/gaia/issues/1716)[#1723](https://github.com/theexperiencecompany/gaia/issues/1723), landed as one) ([#1723](https://github.com/theexperiencecompany/gaia/issues/1723)) ([8ff2293](https://github.com/theexperiencecompany/gaia/commit/8ff2293d14eb97e6fba582ba1b1fdb9dc3a99730))
* **delivery:** presence-aware, one-place proactive messaging ([#1523](https://github.com/theexperiencecompany/gaia/issues/1523)) ([39887cf](https://github.com/theexperiencecompany/gaia/commit/39887cfe9e9fe0b6c7a1fe5daa916cf09eac2b2f))
* **settings:** quiet hours are the user's own, set on a noon-to-noon slider ([#1664](https://github.com/theexperiencecompany/gaia/issues/1664)) ([074b108](https://github.com/theexperiencecompany/gaia/commit/074b1089d6e92d0b64988fbcdbf4b53f13db9939))
* **todos:** give every tracked todo its own chat, led by what woke each run ([#1561](https://github.com/theexperiencecompany/gaia/issues/1561)) ([7fa8464](https://github.com/theexperiencecompany/gaia/commit/7fa84648be37066f58b4929dc0f8a0c468d8f1f9))
* **web:** migrate HeroUI v2 ’ v3 (perf 77’100) ([#1577](https://github.com/theexperiencecompany/gaia/issues/1577)) ([61acd9c](https://github.com/theexperiencecompany/gaia/commit/61acd9c8b6cfacbebb5d161714756addd1dbe991))
* **web:** see, edit and turn off a job's Runs only when rule ([#1661](https://github.com/theexperiencecompany/gaia/issues/1661)) ([e89213c](https://github.com/theexperiencecompany/gaia/commit/e89213c039dfe86ae238d1d0bdf0cbc8b896243a))
* **web:** the visible fixes from the heygaia.io audit ([#1539](https://github.com/theexperiencecompany/gaia/issues/1539)) ([fc67d3d](https://github.com/theexperiencecompany/gaia/commit/fc67d3d8301634b4cd807ab6e3a5ee8c18861bc1))


### Bug Fixes

* **bots:** point every bot link at one set of handles ([#1672](https://github.com/theexperiencecompany/gaia/issues/1672)) ([68858b3](https://github.com/theexperiencecompany/gaia/commit/68858b3cc47eacf4552a860e09050958500231e1))
* **comms:** one GAIA that reacts instead of replying "on it" and never claims unconfirmed work ([#1669](https://github.com/theexperiencecompany/gaia/issues/1669)) ([254537b](https://github.com/theexperiencecompany/gaia/commit/254537b4982dc1d6b2752516a5a3ba8bfd161407))
* **integrations:** connect links show what they connect, Dodo re-registers a forgotten client, and the clients use generated API types ([#1972](https://github.com/theexperiencecompany/gaia/issues/1972)) ([4c4f833](https://github.com/theexperiencecompany/gaia/commit/4c4f8331b6763ffecdb43037115dba0f494ea9bb))
* **onboarding:** one server event per wizard step, retrying answers save, wait for the bot link, log out ([#1591](https://github.com/theexperiencecompany/gaia/issues/1591)) ([735f860](https://github.com/theexperiencecompany/gaia/commit/735f8606c2cdfcabf67d2ee4470bc7f131d6c23a))
* usage stops at 100% of the monthly allowance with a clear reset date; visible attachment limits ([#1582](https://github.com/theexperiencecompany/gaia/issues/1582)) ([fcfa685](https://github.com/theexperiencecompany/gaia/commit/fcfa6850cafff3a21fa27d7148b57bcde0f85618))
* **usage:** budget-wall cards name the wall that bound, and bots relay its message ([#1663](https://github.com/theexperiencecompany/gaia/issues/1663)) ([f97cea1](https://github.com/theexperiencecompany/gaia/commit/f97cea101c56c03adb9ec265dffbc6938f9007f3))
</details>

<details><summary>bots: 1.9.0</summary>

## [1.9.0](https://github.com/theexperiencecompany/gaia/compare/bots-v1.8.0...bots-v1.9.0) (2026-11-28)


### Features

* **api:** a restarted bot resumes the events stream after what it delivered, and voice reads wire 2 ([#1958](https://github.com/theexperiencecompany/gaia/issues/1958)) ([b83dd4b](https://github.com/theexperiencecompany/gaia/commit/b83dd4bb7659762766ab433af0f6eb5db6883947))
* **api:** a stream's request event carries its real bytes, and the bots log their git commit ([#1946](https://github.com/theexperiencecompany/gaia/issues/1946)) ([2bc8074](https://github.com/theexperiencecompany/gaia/commit/2bc807406db36877aaaff59d65cc69d6b13caab6))
* **briefing:** daily and weekly briefs, heygaia.link sharing, and OpenUI artifacts ([#1853](https://github.com/theexperiencecompany/gaia/issues/1853)) ([b0c7d7c](https://github.com/theexperiencecompany/gaia/commit/b0c7d7c38edec5d4d4e7a1b497b792efe5b925ec))
* **ci:** nx decides what CI runs; stop the self-made flakes and silent passes ([#1569](https://github.com/theexperiencecompany/gaia/issues/1569)) ([c722c9c](https://github.com/theexperiencecompany/gaia/commit/c722c9c021df2a050773dfe34cb2d9040bed2aeb))
* **conversation:** the conversation-runtime redesign (stack [#1716](https://github.com/theexperiencecompany/gaia/issues/1716)[#1723](https://github.com/theexperiencecompany/gaia/issues/1723), landed as one) ([#1723](https://github.com/theexperiencecompany/gaia/issues/1723)) ([8ff2293](https://github.com/theexperiencecompany/gaia/commit/8ff2293d14eb97e6fba582ba1b1fdb9dc3a99730))
* **observability:** every alert rule reaches prod, every user-facing failure has a signal, and alerts name what broke ([#1911](https://github.com/theexperiencecompany/gaia/issues/1911)) ([e8ea875](https://github.com/theexperiencecompany/gaia/commit/e8ea8752ea7eda08d6a0d36681ebf7fb41553e32))


### Bug Fixes

* **bots:** a brief's image reaches Telegram as image.jpg, not a download named after its signed URL ([#1966](https://github.com/theexperiencecompany/gaia/issues/1966)) ([e44718d](https://github.com/theexperiencecompany/gaia/commit/e44718dbd363a1a96e1d195ac796f2579bb7c439))
* **bots:** a brief's image reaches Telegram as image.jpg, not as a download named after its signed URL ([e44718d](https://github.com/theexperiencecompany/gaia/commit/e44718dbd363a1a96e1d195ac796f2579bb7c439))
* **bots:** a live preview of a long one-line code block no longer re-splits the same text forever ([#1904](https://github.com/theexperiencecompany/gaia/issues/1904)) ([0343bae](https://github.com/theexperiencecompany/gaia/commit/0343bae3619781761bb21e214a5d30e2fd845e21))
* **bots:** a reaction the bot had not placed is placed once after a restart ([#1962](https://github.com/theexperiencecompany/gaia/issues/1962)) ([cec9faa](https://github.com/theexperiencecompany/gaia/commit/cec9faaeb8dc603df4a0a3725fd07e40c43c9a25))
* **bots:** images reach Telegram and WhatsApp as photos, the way a person sends them ([#1981](https://github.com/theexperiencecompany/gaia/issues/1981)) ([6f17e14](https://github.com/theexperiencecompany/gaia/commit/6f17e140fb91e644d25cffa3710690ae73612c5d))
* **bots:** reading one large conversation event no longer rescans it on every network chunk ([#1913](https://github.com/theexperiencecompany/gaia/issues/1913)) ([335aff2](https://github.com/theexperiencecompany/gaia/commit/335aff29d70abcf8eaf458fe89a2b3d313342862))
* **bots:** ship the identity file in the bot images ([#1677](https://github.com/theexperiencecompany/gaia/issues/1677)) ([c8fbbc9](https://github.com/theexperiencecompany/gaia/commit/c8fbbc91f6629f621f8f4316bdde7f896882dd55))
* **browser:** serve the live view under /api/v1 so its socket upgrades behind every proxy ([#1578](https://github.com/theexperiencecompany/gaia/issues/1578)) ([35625ca](https://github.com/theexperiencecompany/gaia/commit/35625ca019f70c057165ac0a95d2c26780bacba8))
* **comms:** one GAIA that reacts instead of replying "on it" and never claims unconfirmed work ([#1669](https://github.com/theexperiencecompany/gaia/issues/1669)) ([254537b](https://github.com/theexperiencecompany/gaia/commit/254537b4982dc1d6b2752516a5a3ba8bfd161407))
* **deps:** close the open npm Dependabot alerts ([#1630](https://github.com/theexperiencecompany/gaia/issues/1630)) ([7b2c8cd](https://github.com/theexperiencecompany/gaia/commit/7b2c8cdfb6e9b7553ea0d025a139368a46a30b53))
* **integrations:** connect links show what they connect, Dodo re-registers a forgotten client, and the clients use generated API types ([#1972](https://github.com/theexperiencecompany/gaia/issues/1972)) ([4c4f833](https://github.com/theexperiencecompany/gaia/commit/4c4f8331b6763ffecdb43037115dba0f494ea9bb))


### Performance Improvements

* **ci:** web e2e and bot scenarios run in two shards each instead of one 33-minute job ([#1877](https://github.com/theexperiencecompany/gaia/issues/1877)) ([6c5ef98](https://github.com/theexperiencecompany/gaia/commit/6c5ef988fbf187ab671c53f16d1eac1bb248dcc6))
* **conversation:** the events stream sends each card once, changes as patches, and resumes after a head ([#1945](https://github.com/theexperiencecompany/gaia/issues/1945)) ([d85016a](https://github.com/theexperiencecompany/gaia/commit/d85016a7deaa23ad70eaca7276a02398d03d0dff))
* cut our latency around the comms model call on web and bots ([#1831](https://github.com/theexperiencecompany/gaia/issues/1831)) ([837d31b](https://github.com/theexperiencecompany/gaia/commit/837d31b994c23dc5c3566ac906f88aa3b35e3e67))
</details>

<details><summary>cli: 0.8.0</summary>

## [0.8.0](https://github.com/theexperiencecompany/gaia/compare/cli-v0.7.0...cli-v0.8.0) (2026-11-28)


### Features

* **briefing:** daily and weekly briefs, heygaia.link sharing, and OpenUI artifacts ([#1853](https://github.com/theexperiencecompany/gaia/issues/1853)) ([b0c7d7c](https://github.com/theexperiencecompany/gaia/commit/b0c7d7c38edec5d4d4e7a1b497b792efe5b925ec))
* **ci:** nx decides what CI runs; stop the self-made flakes and silent passes ([#1569](https://github.com/theexperiencecompany/gaia/issues/1569)) ([c722c9c](https://github.com/theexperiencecompany/gaia/commit/c722c9c021df2a050773dfe34cb2d9040bed2aeb))
* **conversation:** the conversation-runtime redesign (stack [#1716](https://github.com/theexperiencecompany/gaia/issues/1716)[#1723](https://github.com/theexperiencecompany/gaia/issues/1723), landed as one) ([#1723](https://github.com/theexperiencecompany/gaia/issues/1723)) ([8ff2293](https://github.com/theexperiencecompany/gaia/commit/8ff2293d14eb97e6fba582ba1b1fdb9dc3a99730))


### Bug Fixes

* **cli:** verify GAIA answers before pairing a device ([#1856](https://github.com/theexperiencecompany/gaia/issues/1856)) ([62c4429](https://github.com/theexperiencecompany/gaia/commit/62c442944677644a9a48f63a1b98fb621e316956))
* **cli:** verify GAIA answers before pairing this device ([62c4429](https://github.com/theexperiencecompany/gaia/commit/62c442944677644a9a48f63a1b98fb621e316956))
* **deps:** close the open npm Dependabot alerts ([#1630](https://github.com/theexperiencecompany/gaia/issues/1630)) ([7b2c8cd](https://github.com/theexperiencecompany/gaia/commit/7b2c8cdfb6e9b7553ea0d025a139368a46a30b53))
* **seo:** full-crawl Links and URL Structure to 100, family pages ship half the CSS ([#1797](https://github.com/theexperiencecompany/gaia/issues/1797)) ([dad3377](https://github.com/theexperiencecompany/gaia/commit/dad3377db52ed03387c354463b07094c22c7f935))
* **web:** rebuild public pages the moment a published integration or workflow changes ([#1937](https://github.com/theexperiencecompany/gaia/issues/1937)) ([0d88b89](https://github.com/theexperiencecompany/gaia/commit/0d88b89feec14b2c66a9321da614ce353e004dc4))


### Performance Improvements

* **ci:** self-host e2e runs only when the change reaches the self-host stack ([#1900](https://github.com/theexperiencecompany/gaia/issues/1900)) ([a94e063](https://github.com/theexperiencecompany/gaia/commit/a94e06334391e548a837c4c6361e02c8de16206e))
</details>

---
This PR was generated with [Release Please](https://github.com/googleapis/release-please). See [documentation](https://github.com/googleapis/release-please#release-please).