// Test harness that runs INSIDE the sandbox container (never in the API process).
// Reads {"code", "function", "tests", "per_test_seconds"} as JSON on stdin, runs the candidate's function in a
// separate vm context (no require/process) with a per-test timeout, and prints one marked result line.
"use strict";
const fs = require("fs");
const vm = require("vm");

const MARKER = "__MOCKMATE_RESULT__";
const MAX_CAPTURE = 2000;
const write = process.stdout.write.bind(process.stdout);
const emit = (obj) => write("\n" + MARKER + JSON.stringify(obj) + "\n");

const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const limitMs = Math.round((payload.per_test_seconds || 2) * 1000);
const budgetMs = (payload.budget_seconds || 4) * 1000; // stop before the container's hard CPU limit
const cpuMs = () => {
  const u = process.cpuUsage();
  return (u.user + u.system) / 1000;
};

let captured = "";
const log = (...args) => {
  if (captured.length < MAX_CAPTURE) {
    captured += args.map((a) => (typeof a === "string" ? a : safeJson(a))).join(" ") + "\n";
  }
};
function safeJson(v) {
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

function describe(err) {
  if (err && typeof err === "object" && "message" in err) {
    const m = /solution\.js:(\d+)/.exec(String(err.stack || ""));
    return `${err.name || "Error"}: ${err.message}${m ? ` (line ${m[1]})` : ""}`;
  }
  return String(err);
}

function equal(a, b) {
  if (typeof a === "number" && typeof b === "number") {
    return Math.abs(a - b) <= Math.max(1e-9, 1e-6 * Math.max(Math.abs(a), Math.abs(b)));
  }
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => equal(x, b[i]));
  if (a && b && typeof a === "object" && typeof b === "object" && !Array.isArray(a) && !Array.isArray(b)) {
    const ka = Object.keys(a).sort();
    const kb = Object.keys(b).sort();
    return equal(ka, kb) && ka.every((k) => equal(a[k], b[k]));
  }
  return a === b;
}

function main() {
const sandbox = { console: { log, info: log, warn: log, error: log, debug: log } };
const context = vm.createContext(sandbox);
try {
  vm.runInContext(
    `${payload.code}\n;globalThis.__fn = typeof ${payload.function} === "function" ? ${payload.function} : undefined;`,
    context,
    { filename: "solution.js", timeout: limitMs },
  );
} catch (err) {
  emit({ compile_error: /Script execution timed out/.test(String(err)) ? "Your code took too long to load" : describe(err) });
  return;
}
if (typeof sandbox.__fn !== "function") {
  emit({ compile_error: `Define a function named ${payload.function}` });
  return;
}

const results = [];
for (const test of payload.tests) {
  if (cpuMs() > budgetMs) {
    results.push({ ok: false, output: null, stdout: "", error: "Not run: time budget used up", ms: 0 });
    continue;
  }
  captured = "";
  sandbox.__args = JSON.stringify(test.args);
  let output = null;
  let error = null;
  let ok = false;
  const start = process.hrtime.bigint();
  try {
    const got = vm.runInContext("JSON.stringify(__fn(...JSON.parse(__args)) ?? null)", context, { timeout: limitMs });
    output = got === undefined ? null : JSON.parse(got);
    ok = equal(output, test.expected);
  } catch (err) {
    error = /Script execution timed out/.test(String(err)) ? `Time limit exceeded (${limitMs / 1000} s)` : describe(err);
  }
  results.push({
    ok,
    output,
    stdout: captured.slice(0, MAX_CAPTURE),
    error,
    ms: Math.round(Number(process.hrtime.bigint() - start) / 1e5) / 10,
  });
}
emit({ results });
}

main();
