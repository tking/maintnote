---
name: documentation-asd-ste100
description: >-
  Guides writing, reviewing, and verifying maintnote documentation using the
  ASD-STE100 (Simplified Technical English) standard. Use this skill whenever
  creating, editing, or reviewing user or contributor documentation in README.md,
  CONTRIBUTING.md, or docs/*.md.
---

# `maintnote` Documentation Standard (ASD-STE100)

Follow these rules whenever you write, edit, or review documentation in
`README.md`, `CONTRIBUTING.md`, or `docs/*.md`.

## Target Audience

Write for **software developers, network engineers, and DevOps engineers** who
have a rough idea of what `maintnote` does, without assuming deep knowledge of
RFC 5545 or `draft-gunter-calext-maintenance-notifications-00`:

- Briefly define domain terms (`Provider`, `Consumer`, `UID`, `SEQUENCE`,
  `METHOD`, `ALTREP`, `CalDAV`, `StateStore`, `TicketHandler`) on first use in
  overview pages.
- Include practical integration context for all three roles: Python APIs for
  developers, provider/consumer network maintenance workflows for network
  engineers, and CLI automation (`-` for `stdin`, `--json`, exit codes `0`/`1`,
  persistent `SQLiteStateStore`, idempotent processing) for DevOps engineers.
- Keep all code snippets, CLI commands, and API symbols accurate against
  `src/maintnote/__init__.py` and `src/maintnote/cli.py`.

## ASD-STE100 Writing Rules

### 1. Consistent Vocabulary and Terminology

Use one term per concept across all documentation:

| Preferred Term | Avoid |
| --- | --- |
| `maintenance notification` / `notification` | `notice` |
| `received` | `incoming` |
| `remove` (prose; keep `strip_method*` / `strip-method` for symbols) | `strip`, `sanitize` |
| `get` (prose; keep `fetch_*` for symbols) | `fetch`, `pull`, `retrieve` |
| `more than one` | `multiple` |
| `allow` | `permit`, `let` |
| `make sure` | `ensure` |
| `usually` or `frequently` | `often` |
| `manually` | `by hand` |
| `automatically add events to personal calendars` | `calendar auto-population`, `auto-populate` |
| `directly` | `out of the box` |
| `connect` | `plug in` |
| `for example` | `e.g.`, `i.e.`, `etc.`, `via` |

- Avoid vague or unapproved verbs (`utilize`, `leverage`).
- Use only `can`, `must`, and `will` as modal verbs (avoid `should`, `may`,
  `might`, `could`, `would`).
- Avoid contractions, idioms, em dashes (`—`), and slashes (`/`) meaning "and"
  or "or" in prose.

### 2. Sentence Length and Structure

- **Procedural sentences**: maximum **20 words**. Put one action per sentence.
- **Descriptive sentences**: maximum **25 words**.
- **Paragraphs**: maximum **6 sentences**; one topic per paragraph.
- **Conditions first**: place the condition before the action (`If ..., call ...`,
  `Before you ..., attach ...`).
- **Active voice and imperative mood**: use imperative verbs for instructions
  (`Run`, `Call`, `Install`, `Pass`, `Set`) and active voice for descriptions.
- **Avoid `-ing` participles** as clause connectors or adjectives (except
  established technical nouns like `ticketing`, `routing`, `peering`).
- **Noun clusters**: keep noun clusters to at most **3 nouns** (break up longer
  chains with prepositions).

### 3. Warnings, Cautions, and Notes

- Place `!!! warning` or `!!! caution` blocks **before** the procedure or code
  example they apply to.
- State the required action or hazard clearly along with its consequence.
- Use `!!! note` strictly for supplementary information — **never** put a
  required instruction inside a `!!! note` block.

### 4. MkDocs Link Safety

- Inside `docs/*.md`, link only to other pages in `docs/` using relative paths
  and valid heading anchors. Reference repository files outside `docs/` (such as
  `examples/provider_lifecycle.py`) as inline code rather than Markdown links so
  `mkdocs build --strict` does not fail.
- Inside `README.md`, relative Markdown links to `docs/`, `examples/`, and root
  files are allowed and must resolve to existing files.

## Verification Steps

Before committing documentation changes:

1. Run the ASD-STE100 and link check script:
   ```bash
   python3 .agents/skills/documentation-asd-ste100/scripts/check_docs.py
   ```
   Confirm it reports `0` issues.
2. Build the documentation in strict mode (locally or via CI):
   ```bash
   mkdocs build --strict
   ```
3. Follow the repository Pull Request workflow in `AGENTS.md`.
