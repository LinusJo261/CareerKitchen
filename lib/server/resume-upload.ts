import "server-only";
import { MAX_RESUME_BYTES } from "../onboarding";
import { GatewayError } from "./http-utils";

const MAX_MULTIPART_BYTES = MAX_RESUME_BYTES + 32_000;

/** Bound the stream before parsing it, including requests without Content-Length. */
export async function resumeForm(request: Request): Promise<FormData> {
  const contentType = request.headers.get("content-type") || "";
  if (!contentType.toLowerCase().startsWith("multipart/form-data;"))
    throw new GatewayError(
      415,
      "DOCUMENT_TYPE",
      "Choose a UTF-8 plain text (.txt) resume.",
    );
  if (Number(request.headers.get("content-length") || 0) > MAX_MULTIPART_BYTES)
    throw new GatewayError(413, "DOCUMENT_SIZE", "Choose a resume under 4 MB.");
  if (!request.body)
    throw new GatewayError(
      422,
      "DOCUMENT_REQUIRED",
      "Choose a resume to upload.",
    );
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > MAX_MULTIPART_BYTES) {
        await reader.cancel();
        throw new GatewayError(
          413,
          "DOCUMENT_SIZE",
          "Choose a resume under 4 MB.",
        );
      }
      chunks.push(part.value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  let incoming: FormData;
  try {
    incoming = await new Response(bytes, {
      headers: { "Content-Type": contentType },
    }).formData();
  } catch {
    throw new GatewayError(
      422,
      "INVALID_DOCUMENT",
      "The resume upload could not be read. Choose the file again.",
    );
  }
  const file = incoming.get("file");
  if (
    !(file instanceof Blob) ||
    !("name" in file) ||
    typeof file.name !== "string" ||
    incoming.getAll("file").length !== 1 ||
    [...incoming.keys()].some((key) => key !== "file")
  )
    throw new GatewayError(422, "DOCUMENT_REQUIRED", "Choose one resume file.");
  if (!file.size || file.size > MAX_RESUME_BYTES)
    throw new GatewayError(
      413,
      "DOCUMENT_SIZE",
      "Choose a non-empty resume under 4 MB.",
    );
  if (
    !file.name.toLowerCase().endsWith(".txt") ||
    (file.type && file.type !== "text/plain")
  )
    throw new GatewayError(
      415,
      "DOCUMENT_TYPE",
      "Export your resume as UTF-8 plain text (.txt).",
    );
  const outgoing = new FormData();
  // The API validates UTF-8 and content safety; the browser MIME value is not trusted.
  outgoing.set(
    "file",
    new Blob([await file.arrayBuffer()], { type: "text/plain" }),
    "resume.txt",
  );
  return outgoing;
}
