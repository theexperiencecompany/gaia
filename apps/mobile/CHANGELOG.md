# Changelog

## [0.2.0](https://github.com/theexperiencecompany/gaia/compare/mobile-v0.1.1...mobile-v0.2.0) (2026-01-28)


### Features

* Add a new connect drawer component, integrate it into the chat input ([4f96e06](https://github.com/theexperiencecompany/gaia/commit/4f96e06e082758210b8c553e3fa1fc0f328dbcc6))
* add email compose and accordion components, and update mobile auth callback URI. ([cbbd7ee](https://github.com/theexperiencecompany/gaia/commit/cbbd7ee79792df7d8a3239041abc91dccca1bf8f))
* add NotificationProvider and responsive utilities ([4d621ec](https://github.com/theexperiencecompany/gaia/commit/4d621ec778e57de8164422176d6515b6a811dbfc))
* add NotificationProvider and UI updates ([#422](https://github.com/theexperiencecompany/gaia/issues/422)) ([8608485](https://github.com/theexperiencecompany/gaia/commit/8608485f6e4e3372af6919b1c22cd5cb38804642))
* Centralize authentication logic and types into dedicated API and types files. ([577414a](https://github.com/theexperiencecompany/gaia/commit/577414a986ea9c2c51259d35fddc9a6c26dfe54c))
* Centralize chat API calls and types into a new module and add loading states to the chat UI. ([907b7a3](https://github.com/theexperiencecompany/gaia/commit/907b7a3ba0323d17856d3a2181d53bc00b683dfa))
* Display tool data cards and interactive follow-up actions within chat messages, and update chat stream to support them. ([c9a6de1](https://github.com/theexperiencecompany/gaia/commit/c9a6de1795acb29fda92e02eb952f13a4dc7d3f9))
* Enhance chat functionality with progress indicators, follow-up actions, and improved message handling ([f4c1a4b](https://github.com/theexperiencecompany/gaia/commit/f4c1a4bd736003fc0b4777118bf8e36036004074))
* Implement bearer token authentication for mobile clients, update app configuration ([26d3012](https://github.com/theexperiencecompany/gaia/commit/26d3012473c066b49e21e252c5e322435d1df7d3))
* Implement mobile API client and dynamic chat history ([b6bd5c8](https://github.com/theexperiencecompany/gaia/commit/b6bd5c829d8fc61d092aabb202a5a4cedaa41614))
* Implement playful AI thinking messages and integrate a new loading state into chat bubbles, replacing the standalone progress indicator. ([16fd5b7](https://github.com/theexperiencecompany/gaia/commit/16fd5b7ff057da86d3b83e6d97f14df3a497e1c9))
* Implement secure WebSocket authentication via subprotocols and enhance notification error handling for mobile. ([ac16851](https://github.com/theexperiencecompany/gaia/commit/ac168518566a45b1b1db874a8e03a52c1c49ab15))
* init push noti det up ([1d1e0cd](https://github.com/theexperiencecompany/gaia/commit/1d1e0cd66e09a8ee79c4c186ac00e435af67ca3c))
* Integrate Zustand for state management, enhance chat functionality, and support multi-part messages in chat UI ([386a040](https://github.com/theexperiencecompany/gaia/commit/386a0406589acc072acb03dcef36151f91da6acb))
* Introduce a settings sheet, refactor chat UI components to use styling utilities, and remove the model selector. ([bd1fbdb](https://github.com/theexperiencecompany/gaia/commit/bd1fbdbdc2e186c3b50c43854f0aeb2952b4c355))
* Introduce chat streaming functionality and integreate Hero UI native ([#410](https://github.com/theexperiencecompany/gaia/issues/410)) ([186e0cb](https://github.com/theexperiencecompany/gaia/commit/186e0cbec1344bb218d783da50cb2a1931f7a305))
* Introduce chat streaming functionality with a new SSE client and integrate into chat components. ([19f1078](https://github.com/theexperiencecompany/gaia/commit/19f10787ebe2ff46ac68edbc4854159d624605fb))
* migrate ConnectDrawer from BottomSheet to Popover and simplify root layout views` ([fcbab55](https://github.com/theexperiencecompany/gaia/commit/fcbab5535998007f89dd01b39ab68d20f3ea303c))
* **mobile:** configure custom notification sound (uwu.mp3) ([d7c1276](https://github.com/theexperiencecompany/gaia/commit/d7c12769a47bfb41677793f2ce1b4997f10ab933))
* **notifications:** enhance push notification handling and add Firebase setup instructions ([0c5c299](https://github.com/theexperiencecompany/gaia/commit/0c5c299572d47cbdecfb38fd370976203985d8ea))
* **notifications:** implement real-time notifications via WebSocket and add related hooks ([2756256](https://github.com/theexperiencecompany/gaia/commit/27562566d6ed826161decaadd5d146968106f76c))
* push notification for mobile app ([#421](https://github.com/theexperiencecompany/gaia/issues/421)) ([a00820f](https://github.com/theexperiencecompany/gaia/commit/a00820feafa8288488384d1f9ffdcfcaf4431cb7))
* Refactor chat components for improved functionality and UI consistency, including loading states, message handling, and sidebar interactions. ([8187cda](https://github.com/theexperiencecompany/gaia/commit/8187cdaf7d31d86b75f0a61558b706903e1395ee))
* refactor chat UI by extracting message bubble and input components, and simplifying global CSS colors ([1176d45](https://github.com/theexperiencecompany/gaia/commit/1176d4576e009a8545ab555a5bc2e4c850329829))
* update app configuration and enhance chat functionality with new features ([09933fa](https://github.com/theexperiencecompany/gaia/commit/09933fa7046832cdd53b1a0953c437571640ae29))


### Bug Fixes

* **notifications:** refactor push notification setup and improve token management ([5f465a3](https://github.com/theexperiencecompany/gaia/commit/5f465a3e251be3db89f2cfd6752153c5413bfb4e))
* sensitive bar visualizer bug fixed ([9af70b2](https://github.com/theexperiencecompany/gaia/commit/9af70b2333f53be1b767360b34a6461bc4a1eccb))
* Use router.replace instead of router.push in handleSelectChat to prevent page stacking ([300e2d1](https://github.com/theexperiencecompany/gaia/commit/300e2d15cf76011f3ca99d8a4e676faa85fdf076))
