import type { createCareerKitchenClient } from "../src/index.js";

// Compiled only: changing the generated contract must retain these negative guarantees.
function contractTypeAssertions(client: ReturnType<typeof createCareerKitchenClient>) {
  // @ts-expect-error unknown routes cannot compile
  void client.GET("/v1/nonexistent");
  // @ts-expect-error version is required for a pause transition
  void client.POST("/v1/candidates/me/pause", { params: { header: { "Idempotency-Key": "stable-operation" } }, body: {} });
  // @ts-expect-error every mutation requires its idempotency header
  void client.POST("/v1/candidates/me/pause", { body: { expected_version: 1 } });
  // @ts-expect-error an upload requires a Blob, not a string pretending to be a file
  void client.uploadMultipart("/v1/candidates/me/resume", { params: { header: { "Idempotency-Key": "stable-operation" } }, body: { file: "not-a-file" } });
}
void contractTypeAssertions;
