import { readFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const directory = await mkdtemp(join(tmpdir(), "career-kitchen-types-"));
try {
  const output = join(directory, "schema.ts");
  const command = new URL("../node_modules/openapi-typescript/bin/cli.js", import.meta.url);
  const schema = new URL("../../../docs/openapi.json", import.meta.url);
  const result = spawnSync(process.execPath, [fileURLToPath(command), fileURLToPath(schema), "-o", output, "--alphabetize"], { encoding: "utf8" });
  if (result.status !== 0) throw new Error(result.stderr || "Type generation failed");
  const current = await readFile(new URL("../src/schema.ts", import.meta.url), "utf8");
  const generated = await readFile(output, "utf8");
  if (current.replace(/\r\n/g, "\n") !== generated.replace(/\r\n/g, "\n")) {
    throw new Error("Generated client types changed. Run npm run generate in packages/api-client.");
  }
  console.log("Generated TypeScript types match OpenAPI");
} finally {
  if (dirname(resolve(directory)) !== resolve(tmpdir()) || !basename(directory).startsWith("career-kitchen-types-")) {
    throw new Error("Refusing to remove an unexpected temporary directory");
  }
  await rm(directory, { recursive: true, force: true });
}

