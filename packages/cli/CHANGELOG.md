# Changelog

## [0.2.0](https://github.com/theexperiencecompany/gaia/compare/cli-v0.1.10...cli-v0.2.0) (2026-02-20)


### Features

* Add `--branch` option to the `init` command for specifying the Git branch to clone. ([5b04594](https://github.com/theexperiencecompany/gaia/commit/5b0459491285cc2f71bba591a95dab956e4a4b3f))
* Add Bots, CLI, Added skills in codebase ([#487](https://github.com/theexperiencecompany/gaia/issues/487)) ([206675b](https://github.com/theexperiencecompany/gaia/commit/206675bf79e41da50e9f1870e854783a22dee785))
* add logging functionality to service start flow and UI display ([f2dc69a](https://github.com/theexperiencecompany/gaia/commit/f2dc69aac558b5a261a8ace62b5d012abe748737))
* basic support for cli ([71414e8](https://github.com/theexperiencecompany/gaia/commit/71414e86a85967eebbe20886d6b36f558c6ea0e6))
* CLI (Command LIne Interface) to make it easy to self-host and contribute ([#431](https://github.com/theexperiencecompany/gaia/issues/431)) ([c6772df](https://github.com/theexperiencecompany/gaia/commit/c6772dfd60f1e60e7d559638ff133d40b3a65909))
* **cli:** add status and stop commands with UI integration ([547ba8a](https://github.com/theexperiencecompany/gaia/commit/547ba8a99a36e44c71544b221a989e706899c434))
* **cli:** enhance initialization flow with new steps and improved state management ([24c8d53](https://github.com/theexperiencecompany/gaia/commit/24c8d53352534ba8a4713adeb2c642b411f14d79))
* enhance CLI initialization flow with logging and Docker support; add Docker build workflow ([d6e2e05](https://github.com/theexperiencecompany/gaia/commit/d6e2e0572558a3203388ee832332f14a2ad6430b))
* Enhance CLI initialization with port checks, earlier tool installation, detailed logging, explicit self-host startup, and post-start health verification. ([de1a2b3](https://github.com/theexperiencecompany/gaia/commit/de1a2b3aac0e99781d7a9ed8715c610c063e1097))
* enhance CLI publish workflow and state management with throttling ([0efd309](https://github.com/theexperiencecompany/gaia/commit/0efd309181b7835d694e179599c48fc9bf156d4b))
* enhance Docker prerequisite checks with detailed error messages ([d84fd33](https://github.com/theexperiencecompany/gaia/commit/d84fd33a931dc3caec916d98de15a80bd3f32b1c))
* enhance environment setup and error handling ([7be7a71](https://github.com/theexperiencecompany/gaia/commit/7be7a71da4bdb61c664f62b6c373ca34e995b23d))
* enhance repository setup with detailed cloning progress and phases ([7598810](https://github.com/theexperiencecompany/gaia/commit/759881009feb4b67a1319a830891732c6ba92966))
* fix CLI docs, install script, and port conflict handling ([243727c](https://github.com/theexperiencecompany/gaia/commit/243727c1bb18493223cec0e773116950bef5e464))
* Introduce a dedicated CLI installation page and migrate CLI packaging from Bun to npm. ([934f9e2](https://github.com/theexperiencecompany/gaia/commit/934f9e2d34dfa6037770b61f0153ec6a938ac257))
* overhaul CLI UX — reorder init flow, simplify UI, deduplicate components ([65edace](https://github.com/theexperiencecompany/gaia/commit/65edaceef22559887a8bda56f2afd5de1bcf5470))
* Prioritize CLI setup in documentation and update core configurations and scripts. ([3e116d9](https://github.com/theexperiencecompany/gaia/commit/3e116d91f241865ee8227c71a5f9c565b0f8bb7c))
* Remove interactive service startup and health check, providing manual instructions for starting GAIA. ([e55c696](https://github.com/theexperiencecompany/gaia/commit/e55c696de0f7245fff2473b690811ba6ae21d203))
* update API base URL and WebSocket handling ([1db7fbe](https://github.com/theexperiencecompany/gaia/commit/1db7fbe4a75216e411b3936ef0ad0f8fabaa0a82))
* update CLI version to 0.1.1 and add new scripts for type checking, linting, and formatting ([233a3d3](https://github.com/theexperiencecompany/gaia/commit/233a3d34b3a68099d63484920b9b947856892a22))
* update CLI version to 0.1.4 in manifest and package.json ([51c36e6](https://github.com/theexperiencecompany/gaia/commit/51c36e6aae86e9e55825ce9a8ef4f0a26402f94c))
* update CLI version to 0.1.8 and enhance setup flows with exit prompts and environment setup feedback ([e0b85ce](https://github.com/theexperiencecompany/gaia/commit/e0b85ce994ae47f817d295b6771f9ff57bb8cdca))
* update CLI version to 0.1.9, enhance setup flow with existing repo handling and configuration management ([8de4019](https://github.com/theexperiencecompany/gaia/commit/8de401955e0fae546b3aabc0373086a99b9a1ec1))
* update Docker configurations and CLI commands for improved service management ([9ed98cd](https://github.com/theexperiencecompany/gaia/commit/9ed98cd6aa325507b075059d3ccf912117b25ce9))


### Bug Fixes

* bigtext not showing properly in commands ([9618cf8](https://github.com/theexperiencecompany/gaia/commit/9618cf8a46647f76b3d8d6a9de11433715693877))
* **cli:** add optional timeout to waitForInput to prevent infinite hang ([17dec1b](https://github.com/theexperiencecompany/gaia/commit/17dec1befc027e6b6f74f3ad12236443b3c5d29e))
* **cli:** add SIGINT/SIGTERM handlers for graceful shutdown in all commands ([a7387d1](https://github.com/theexperiencecompany/gaia/commit/a7387d1ec6bd83be7b2c9a178f2ad2eac5d36c6e))
* **cli:** bump version to 0.1.14 ([78eb6aa](https://github.com/theexperiencecompany/gaia/commit/78eb6aa3145f38e3a8bffcd70ce185190c3e1be0))
* **cli:** bump version to 0.1.15 ([0897ce0](https://github.com/theexperiencecompany/gaia/commit/0897ce018366e71962fb04d7c5d3a571b5982941))
* **cli:** comprehensive audit fixes for all critical and significant issues ([a1e4fda](https://github.com/theexperiencecompany/gaia/commit/a1e4fda41a2abf99a129640bd34284a836856ac5))
* **cli:** enhance documentation with upgrade and uninstall instructions, add options for commands ([5b0a5ca](https://github.com/theexperiencecompany/gaia/commit/5b0a5ca5495d535a5689f13500c00bbf4deba205))
* **cli:** extract log buffer sizes to shared constant to reduce memory pressure ([29975c7](https://github.com/theexperiencecompany/gaia/commit/29975c79318a313f31fd2de8cb8f59ffb268e8ee))
* **cli:** improve LogWindow React key stability to reduce unnecessary re-renders ([fed5702](https://github.com/theexperiencecompany/gaia/commit/fed57024f2f6b484afd555404f43307aa4ca70eb))
* **cli:** reset isRefreshing when service data updates, not just on step change ([19f9206](https://github.com/theexperiencecompany/gaia/commit/19f92061d9edf262db0ff65e7face5abc66261e7))
* **cli:** use CLI_VERSION in developer mode writeConfig, handle rmSync failure, surface pull error reason ([3224f9e](https://github.com/theexperiencecompany/gaia/commit/3224f9e519b7ef08aac3094b4c45e7d65ee359eb))
* **cli:** validate port numbers are within valid range 1-65535 ([5377408](https://github.com/theexperiencecompany/gaia/commit/537740859e099bb177827b1b4747b80c6b21de79))
* remove default --build from docker start, add multi-PM PATH detection and Windows support ([92ed195](https://github.com/theexperiencecompany/gaia/commit/92ed19543c5ce648820c945274b208525d7ac964))
* resolve 11 bugs across CLI init/start/stop/status lifecycle ([4be0995](https://github.com/theexperiencecompany/gaia/commit/4be09954179bf5c951e8687b54556fbc5264844f))
* update version to 0.1.13 in package.json; enhance step labels and add loading message in init screen ([c378db2](https://github.com/theexperiencecompany/gaia/commit/c378db21a1c5f2fb8e80e2ee4f3366473ec79885))
