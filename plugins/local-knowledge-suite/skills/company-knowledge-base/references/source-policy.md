# Company source policy

## Local files

Accept PDF, DOCX, XLSX, PPTX, EML, Markdown, and text. Recursively ingest only supported files from a registered folder. Keep originals in place and identify versions by SHA-256 content hash.

Place approved local material under `COMPANY_ROOT\.local-sources\`, which is
machine-local and ignored by Git. Register files and folders with an existing
absolute Windows path inside that directory. Reject `.ckb/`, `.memorizer/`,
`.local-knowledge/`, `.git/`, canonical `knowledge/`, another registered
company, or any symlink, junction, or reparse-point traversal. Revalidate the
boundary and every selected file when the job runs; relative, missing, swapped,
or escaped paths fail closed.

Published local citations use
`company-source://COMPANY_ID/PATH_RELATIVE_TO_LOCAL_SOURCES`, so their identity
does not contain a drive letter. Source files remain outside Git. After a clone,
restore the approved files at the same relative path and ingest them again.
Recall checks that the current local file still has the ingested SHA-256 and
that the citation matches the stored document chunk; changed, missing, or
redirected files immediately fail the evidence gate.
Database rebuild preserves canonical claim history and citation metadata only
as unverified review material; it never treats `verified: true` in Markdown as
independent source proof. Website claims likewise require a new authorized
crawl. Do not edit citation metadata or integrity digests by hand.

Use pinned `pypdfium2` for page text extraction and render low-text pages to
PNG for Tesseract OCR. Require Vietnamese and English Tesseract language packs
for bilingual scans and report OCR readiness through `health`. A malformed PDF
must fail without publishing partial or empty invented content.

## Public websites

- Require explicit HTTP(S) seed URLs and explicit allowlisted domains.
- Restrict navigation to allowed domains and their subdomains.
- Reject localhost, private, link-local, and reserved network addresses.
- Honor `robots.txt`, redirects, depth/page limits, crawl delay, and byte limits.
- Ingest public pages only. Never attach cookies, passwords, browser sessions, or intranet authentication.
- Ignore non-HTML responses; register downloaded files separately.

## Privacy and company isolation

Use only configured local LM Studio chat and embedding endpoints. Do not send source text, citations, prompts, operational logs, accounts, search history, or embeddings to cloud services.

Do not ingest one company's source into another company's repository. Check `company_id` before every mutation. Keep secrets out of source records, OKF concepts, Git, command arguments, and logs; configure credentials through the encrypted portal endpoints backed by Windows Credential Manager.
