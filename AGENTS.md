# AGENTS.md

Utility-bill tracker for Russian ЖКХ (ЕПД). Django REST + Celery parse uploaded PDFs with pdfplumber and regexes (no AI); Next.js serves the UI and proxies `/api` to Django; nginx sits in front. Data is personal (ФИО, address, account number) and money.

## Working an issue

Every change ships as one PR that closes one GitHub issue. Steps, in order:

1. **Claim.** The issue is open, labelled `ready-for-agent`, has no `in-progress` label, and every issue it is blocked by is closed (`gh api repos/TurtleOld/rent/issues/<n> --jq .issue_dependencies_summary`). Add `in-progress` as your first write: all agents share one GitHub account, so the label, not the assignee, marks ownership. Done when the label is on.
2. **Branch** from fresh `origin/main`: `<type>/<slug>`, e.g. `fix/login-csrf`. The slug names the change in words; the issue link lives in the PR body.
3. **Build** exactly the issue's acceptance criteria. Anything else you notice goes into a new issue labelled `needs-triage`, linked from your PR. New or changed logic (parser, money, auth, data writes) gets a test that goes red without your change.
4. **Verify** with the commands below. Done when backend tests and the frontend build are green on your branch and every acceptance criterion has evidence (a test name, command output, or a manual check you actually ran).
5. **Open the PR.** Title is an English Conventional Commit; it becomes the squash commit on `main`. Body is in Russian, written with the `pr` skill template (Кратко / Доказательства / Риск слияния), plus `Closes #<n>`, the acceptance criteria as a checklist with evidence per item, and a «Не проверено» line naming anything you could not check. A human reviews and merges: leave auto-merge off.
6. **Blocked or unsure?** Under Orca supervision, ask through the preamble's `ask` command. Otherwise comment the question on the issue, swap `in-progress` for `needs-info`, and stop.

Under Orca supervision the injected preamble owns the lifecycle (heartbeats, `ask`, `worker_done`); this file owns how the code change is made.

## Commands

Backend tests, same as CI. Use Python 3.12: on 3.13 `psycopg2-binary` 2.9.9 fails to build.

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
SECRET_KEY=ci-only-secret DEBUG=False DATABASE_URL=sqlite:////tmp/ci.sqlite3 MEDIA_ROOT=/tmp/media \
  .venv/bin/python manage.py test tests
```

Frontend (Node 20, as in the Dockerfile):

```bash
cd frontend && npm ci && npm test && npm run build
```

`npm run build` rewrites `frontend/tsconfig.json` and `frontend/next-env.d.ts`; restore them with `git checkout --` unless your issue is about them. `npm run lint` is broken (`next lint` was removed in Next 16), so the build's type check is the frontend gate.

Test PDFs are synthetic and come from `backend/tests/generate_fixtures.py` (needs `reportlab` and a DejaVu/Liberation font; not in `requirements.txt`). Commit regenerated fixtures together with the generator change. Real ЕПД never enter the repo, logs, issues or PRs.

## Code rules

- **Money and quantities** are `Decimal` end to end; parse Russian numbers with the parser's existing helper.
- **Schema changes** come with a new migration; applied migrations stay as they are.
- **User-facing text** (UI, API error messages, invoice warnings), docstrings and comments are Russian; identifiers and commit messages are English.
- **Comments** carry only the why the code cannot show: a domain rule, a PDF quirk, a non-obvious limit. Self-explanatory code stands without them.
- **Docstrings** follow Google style in Russian, with the section headers (`Args:`, `Returns:`, `Raises:`) as Google writes them:

  ```python
  def normalize_unit(raw: str | None) -> str | None:
      """Приводит запись единицы из PDF к канонической форме.

      Args:
          raw: Сырая строка единицы измерения из PDF.

      Returns:
          Каноническая форма единицы или None, если строка не распознана.
      """
  ```
- **Secrets** live in `.env`, which is gitignored; new settings go through `decouple.config` with a safe default and a line in `.env.example` and the README env table.
- **Commits** follow the history's Conventional Commits style (`fix(invoices): ...`, `chore(deps): ...`) and describe only the code change. Commit messages and PR bodies carry no AI attribution: no `Co-Authored-By` for an AI, no "Generated with", no session links.

## `main` is protected

A ruleset allows changes only through a squash-merged PR with these checks green: `Backend tests`, `Backend`, `Nginx`, `Frontend`. The branch must be up to date with `main` (`gh pr update-branch <n>`), and review threads resolved. Renaming one of those CI jobs leaves every PR waiting on the old name; a rename PR must also update the ruleset.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for TurtleOld/rent (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix, plus `in-progress` for claimed work. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` + `docs/adr/`. See `docs/agents/domain.md`.
