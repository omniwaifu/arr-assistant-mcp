import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { v0_4 } from "@anthropic-ai/mcpb/schemas";

const manifest = JSON.parse(readFileSync(new URL("../../manifest.json", import.meta.url)));
const schema = v0_4.McpbManifestSchema;

// MCPB currently requests Zod 3; exercise the schema under our patched Zod 4 override.
test("manifest validation preserves runtime arguments and sensitive configuration", () => {
  assert.deepEqual(schema.parse(manifest), manifest);
});

for (const [name, mutate] of [
  ["invalid runtime", (value) => { value.server.type = "invalid"; }],
  ["non-string environment value", (value) => { value.server.mcp_config.env.RADARR_URL = 42; }],
  ["invalid user configuration", (value) => { value.user_config.radarr_api_key.sensitive = "true"; }],
  ["unknown field", (value) => { value.unexpected = true; }],
  ["missing entry point", (value) => { delete value.server.entry_point; }],
]) {
  test(`manifest validation rejects ${name}`, () => {
    const invalid = structuredClone(manifest);
    mutate(invalid);
    const result = schema.safeParse(invalid);
    assert.equal(result.success, false);
    assert.ok(result.error.issues.length > 0);
  });
}
