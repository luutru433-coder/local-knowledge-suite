# Skills, MCP, and data

## What is a Skill?

A Skill is an operating guide for Codex. It defines what to check, which tool
to use, what counts as a safe result, and when to stop.

| Skill | Purpose |
| --- | --- |
| `manage-local-knowledge` | Route, initialize, check, and recall. |
| `memorizer` | Capture, correct, find, and maintain one project's Memory. |
| `company-knowledge-base` | Ingest, review, search, and publish cited company knowledge. |

A Skill is not company data and is not conversation history.

## What is MCP?

MCP lets Codex call stable plugin functions. Think of four buttons:

1. `bootstrap_workspace` prepares a project;
2. `knowledge_status` checks health and compatibility;
3. `recall_context` searches separate knowledge classes; and
4. `capture_memory` saves one durable project signal.

Compared with manual copy and paste, MCP reduces path and format mistakes,
checks project/company identity, returns clearly separated results, makes
retries idempotent, and enforces redaction, distillation, and citation gates.

It cannot make a wrong document true, replace human review, or turn Git history
into source verification.

## Never conflate the three classes

| Class | Contains | Scope |
| --- | --- | --- |
| Skill | Workflow instructions | Plugin |
| Memory | Preferences, decisions, conventions | One project |
| Company Knowledge | Evidence-backed company facts | One company, many projects |

“This project uses REST” is Memory. “The bicycle warranty is 24 months” must
come from cited Company Knowledge. “Search before capture” is a Skill rule.

## Profiles

- `memory-only`: Memory only; no company; v1 default.
- `combined`: project Memory plus company evidence; requires `company_id`.
- `company-only`: company evidence only; requires `company_id`.

Do not hand-edit a profile, identity, or schema to reassign a project. Use the
supported migration or initialize it correctly.
