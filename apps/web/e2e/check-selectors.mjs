#!/usr/bin/env node
// Fails on fragile Playwright selectors. Usage: node check-selectors.mjs [dir ...]  (default: e2e)
// shortcut: line-regex scan, not an AST; upgrade if multi-line locator calls slip through.
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { join } from "node:path";

const RULES = [
  [/locator\(\s*['"`]\s*\./, "CSS class selector: use getByRole/getByLabel/getByText/getByTestId"],
  [/\[class[*^$~|]?=/, "attribute selector on class"],
  [/nth-child|nth-of-type/, "positional CSS selector"],
  [/locator\(\s*['"`]\s*(\/\/|xpath=)/, "xpath selector"],
  [/waitForTimeout\(/, "fixed sleep: wait on a web-first assertion instead"],
];

const dirs = process.argv.slice(2).length ? process.argv.slice(2) : ["e2e"];
const files = [];
const walk = (p) => {
  if (!existsSync(p)) return;
  if (statSync(p).isDirectory()) {
    if (/node_modules|\.auth$/.test(p)) return;
    for (const f of readdirSync(p)) walk(join(p, f));
  } else if (/\.(ts|tsx|js|mjs)$/.test(p) && !/check-selectors/.test(p)) files.push(p);
};
dirs.forEach(walk);

const bad = [];
for (const f of files)
  readFileSync(f, "utf8").split("\n").forEach((line, i) => {
    for (const [re, msg] of RULES) if (re.test(line)) bad.push(`${f.replaceAll("\\", "/")}:${i + 1}: ${msg}\n    ${line.trim()}`);
  });

if (bad.length) { console.error(`selector check FAILED (${bad.length}):\n${bad.join("\n")}`); process.exit(1); }
console.log(`selector check OK (${files.length} files)`);
