/**
 * skills-symlink — .claude/skills stays a symlink to .agents/skills, so every
 * agent surface reads one copy of each skill. A tracked second copy drifted
 * apart skill by skill before this gate existed.
 */
import { lstatSync, realpathSync } from "node:fs";

const SKILLS_VIEW = ".claude/skills";
const SKILLS_SOURCE = ".agents/skills";
const FIX = `rm -rf ${SKILLS_VIEW} && ln -s ../${SKILLS_SOURCE} ${SKILLS_VIEW} (move any skill only in ${SKILLS_VIEW} into ${SKILLS_SOURCE} first)`;

function fail(reason) {
  console.error(`❌ skills-symlink gate FAILED — ${reason}`);
  console.error(`Fix: ${FIX}`);
  process.exit(1);
}

/** Fails unless .claude/skills is a symlink resolving to .agents/skills. */
export function runSkillsSymlink() {
  let view;
  try {
    view = lstatSync(SKILLS_VIEW);
  } catch {
    fail(`${SKILLS_VIEW} does not exist.`);
  }
  if (!view.isSymbolicLink()) {
    fail(`${SKILLS_VIEW} is a real ${view.isDirectory() ? "directory" : "file"}, not a symlink.`);
  }

  let target;
  try {
    target = realpathSync(SKILLS_VIEW);
  } catch {
    fail(`${SKILLS_VIEW} is a dangling symlink.`);
  }
  let source;
  try {
    source = realpathSync(SKILLS_SOURCE);
  } catch {
    fail(`${SKILLS_SOURCE} does not exist.`);
  }
  if (target !== source) {
    fail(`${SKILLS_VIEW} resolves to ${target}, not ${SKILLS_SOURCE}.`);
  }

  console.log(`✅ skills-symlink: ${SKILLS_VIEW} -> ${SKILLS_SOURCE}`);
}
