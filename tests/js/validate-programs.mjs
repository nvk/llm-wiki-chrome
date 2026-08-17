import process from "node:process";

import {validateProgram} from "../../extension/protocol.mjs";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const programs = JSON.parse(input);
if (!Array.isArray(programs)) throw new Error("Expected an array of synthetic programs.");

const decisions = [];
for (const program of programs) {
  try {
    await validateProgram(program);
    decisions.push(true);
  } catch (_error) {
    decisions.push(false);
  }
}
process.stdout.write(`${JSON.stringify(decisions)}\n`);
