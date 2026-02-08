#!/usr/bin/env bun

/**
 * GAIA CLI Entry Point
 * Main executable for the GAIA command-line interface.
 * @module cli
 */

import { runInit } from "./commands/init/handler.js";

/**
 * Main entry point.
 * Currently defaults to the 'init' command.
 * Future: Add argument parsing with commander or yargs.
 */
runInit();
