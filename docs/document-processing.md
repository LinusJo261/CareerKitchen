# Résumé text extraction

UTF-8 text uses the existing bounded validator. PDF and DOCX still require an
actual successful ClamAV scan; absent/unavailable scanning returns `503` and never
reaches the extractor. Successful binary validation invokes a separate extraction
process before encrypting/storing the original private file. Extracted text is an
untrusted proposed draft, capped independently of file storage, and never changes
skills, evidence status or other authoritative profile fields automatically.

The PDF implementation uses maintained `pypdf>=6.21.1,<7` and its documented
`PdfReader`/`extract_text` APIs. It rejects encrypted files and bounds page count
and expanded content-stream bytes. It performs no OCR: a blank or image-only
document, unsupported format detail, parser failure or exceeded limit yields no
suggested text, so manual entry is required. The original scanned private document
can still be retained for its separately authorized workflow.
[pypdf extraction documentation](https://pypdf.readthedocs.io/en/stable/user/extract-text.html),
[maintainer package release](https://pypi.org/project/pypdf/).

DOCX extraction reads only plain `word/document.xml` text. It never follows
relationships or expands an archive onto disk, rejects duplicate document entries,
DTD/entities, alternative NUL-separated XML encodings, active embedded content,
external relationships and oversized/compression-bomb archives. No URL, executable,
macro, instruction, or tool call embedded in document text is executed.

Default process limits are:

| Resource | Limit |
| --- | --- |
| Input bytes | 10 MB, also subject to the upload limit |
| PDF pages | 20 |
| Expanded PDF streams / DOCX archive | 20 MB |
| Returned draft | 25,000 characters; API summary further capped at 3,000 |
| Child output pipe | 200,000 bytes |
| Wall time | 5 seconds |
| CPU time | 3 seconds |
| Child address space / Windows process memory | 256 MiB |

The child receives document bytes through stdin, starts in an empty temporary
directory with an isolated Python interpreter, and inherits only required Windows
system directory variables. Database, Supabase, encryption, provider credentials,
home directories and application `PYTHONPATH` are not passed. Its trusted dependency
directory comes from the launcher's interpreter configuration, not the document.
Parent output draining is byte-bounded; stderr and parser diagnostics are discarded
without logging private résumé contents.

Linux applies `RLIMIT_AS`, CPU, output-file and core-dump limits before parsing.
Windows applies a Job Object with process memory, CPU time, one-process and
kill-on-close limits before sending any document bytes. If Windows cannot establish
the job restrictions, extraction abstains instead of parsing without a memory cap.
A Python audit hook denies socket/DNS and process-execution APIs in the child.

These are process, resource and Python-level controls. They are not a complete
operating-system network/filesystem sandbox or a substitute for dependency updates,
malware scanning, container permissions and deployment network policy. Current
verification ran the actual Windows Job Object path; Linux limits are implemented
but were not executed on the Windows development host.

```powershell
.venv/Scripts/python.exe -m pytest apps/api/tests/unit/test_document_extract.py -q
```
