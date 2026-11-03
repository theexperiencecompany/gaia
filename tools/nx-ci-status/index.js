// The nx plugin behind the per-check commit statuses: nx prints each task's
// result but keeps none, so after a run this writes them where
// `runner.py run-job` reads them. Off a run-job (no NX_CI_TASK_RESULTS) it does nothing.
const { writeFileSync } = require("node:fs");

const RESULTS_ENV = "NX_CI_TASK_RESULTS";

/** @type {import("nx/src/project-graph/plugins/public-api").PostTasksExecution} */
async function postTasksExecution(_options, context) {
  const target = process.env[RESULTS_ENV];
  if (!target) return;
  const results = Object.fromEntries(
    Object.entries(context.taskResults).map(([task, result]) => [
      task,
      {
        status: result.status,
        code: result.code,
        output: result.terminalOutput ?? "",
      },
    ]),
  );
  writeFileSync(target, `${JSON.stringify(results, null, 2)}\n`);
}

module.exports = { name: "nx-ci-status", postTasksExecution };
