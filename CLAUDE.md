## Agent skills

### Issue tracker

Issues and specs live as local markdown files under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default triage roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), recorded as a `Status:` line in each issue file. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Development

- Run the tests: `uv run pytest`
- Tests drive Mailroom through the web page with a scripted fake Modem (`tests/support.py`); no hardware is needed.
- Run against the attached Modems: `uv run python -m mailroom` (serves `http://127.0.0.1:8000`; override with `MAILROOM_PORT`, and the database path with `MAILROOM_DB`). Only one process can hold the Modems at a time.
