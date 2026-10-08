# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A prototype of the new Bulk Media Uploader (BMU) for UC Berkeley's CollectionSpace tenants, replacing the legacy
`uploadmedia` Django webapp. Museum staff sign in with their own CollectionSpace account, add media files to a job,
edit each document, and submit the job; a worker later creates the Media record, the Blob, the Object (when asked)
and the Relations in CollectionSpace. It implements the design for PAHMA. `README.md` describes what it does and how
to run it; `deploy/README.md` covers AWS.

## Rules that are not negotiable

- **The museum comes from the session or the job, never from the deployment or the browser** (design doc: "One
  deployment for several museums"). One deployment serves several museums: `Services.tenants` holds each one's
  configuration and `Services.readers` its read-only account; use `sess.museum(s)` (or `s.tenants[job["tenant"]]`),
  `sess.client(s)`, staging and thumbnail keys built from the job's museum, and the encryption contexts
  `session_context` and `job_context`, which include the museum. There is no deployment-wide tenant. A new endpoint
  that reads a job must go through `_job_or_404` (it refuses another museum's job), and gets a case in
  `tests/test_museums.py`.
- **The BMU is create-only.** It never deletes or cleans up anything in CollectionSpace. Deleting a job or a document
  removes it from the BMU only.
- **Credentials are the user's own**, HTTP Basic only. A password is never stored permanently: it is encrypted at
  rest (session key while signed in, job key while a job waits or runs) and deleted when the run ends.
  - **The one exception** (decided 4 October 2026; design doc: "Roles", the read-only service account): one
    CollectionSpace account per museum whose role (BMU_Reader) can read and nothing else. It is used only for the
    lookups an intern's draft needs, because an intern's own account has no permissions. Its sign-in is a secret
    in AWS Secrets Manager that only the web app's task role may read; it is fetched when needed, kept in memory for a
    few minutes, and never written to a table, a file or a log. Staff always use their own sign-in, and every write
    to CollectionSpace uses the submitting staff member's. Don't widen this: no other use of the account, no second
    stored account, and never a write with it.
- **No hard-coded list values, and no creating vocabulary or authority terms.** Media types, languages, persons and
  organizations are read from CollectionSpace; per-tenant settings are in `backend/bmu/tenants/<tenant>.yaml`.
- **Never read `.env` files, and never put a login, token or AWS key in the repo, a test or a chat.** Tests use the
  simulated CollectionSpace's accounts (`admin`, `limited`, `reader`).
- **Never commit to `main`.** Work on a feature branch and open a pull request. Before committing to a branch,
  `git fetch` and check whether it was already pushed or merged; never amend or rebase a pushed branch.
- The repository owner runs `git push`, `gh pr create` and every `./bmu aws` command himself: give him the exact
  commands instead of running them.

## Commands

```bash
# Backend (Python 3.11, as in .python-version; FastAPI)
cd backend && pip install --require-hashes -r requirements-dev.txt && pip install --no-deps --no-build-isolation -e .
pytest -q                                   # all tests (about a minute; no network needed)
pytest -q tests/test_row_delete.py          # one file
pytest -q tests/test_flow.py::test_name     # one test

# Frontend (Node 22, Vue 3 + TypeScript)
cd frontend && npm ci
npm run lint                                # ESLint (BOA's rules); npm run lint-fix to fix
npm run typecheck                           # vue-tsc
npm test                                    # Vitest, all files
npx vitest run src/__tests__/finished.test.ts   # one file
npm run build                               # production build (no Demo tools)
npm run build:demo                          # build with Demo tools

# Local environments (Docker)
./bmu up sim        # simulated CollectionSpace, Demo tools on → http://localhost:5173
./bmu up qa         # against the PAHMA QA tenant: creates real records → http://localhost:5273
./bmu down sim|qa|all
./bmu logs sim web  # services: web, worker, frontend, fakecspace, s3, dynamodb
```

CI (`.github/workflows/ci.yml`) runs `pytest -q`, then `npm run lint`, `typecheck`, `test` and `build`, and a
`dependencies` job: the requirements files are in step (below) and `pip-audit` finds no known vulnerabilities, and a
`terraform` job: `terraform fmt -check`, `validate` for both configurations in `deploy/terraform`, and `terraform test`
for the app's (no AWS sign-in; the Terraform version is pinned in the job). After changing a `.tf` file, run
`terraform fmt -recursive deploy/terraform`.
`.github/workflows/audit.yml` repeats the audit, with `npm audit`, every Monday.
A pull request that changes only documentation (`docs/`, `*.md`, `LICENSE`, issue/PR templates) skips `backend`,
`frontend` and `terraform`; the `changes` job decides, and a skipped job counts as passing. `dependencies` and
`.github/workflows/security.yml` (`gitleaks` over the whole history, and `npm audit`) run on every pull request and
push, whatever changed: never add a path filter or a docs-only condition to them. A gitleaks match that isn't a
secret goes in `.gitleaksignore`, by fingerprint, with a comment saying why. Actions are pinned by commit SHA with
the version in a comment; Dependabot moves both.

### Backend dependencies (pinned)

- `backend/pyproject.toml` lists what the code needs, with minimum versions. Every install (CI, both Dockerfiles,
  local) uses exact versions with hashes instead: `requirements.txt` (the app, plus setuptools to build it),
  `requirements-dev.txt` (the app's pins plus pytest, moto, python-hcl2) and `requirements-tools.txt` (pip-tools
  and pip-audit, from `requirements-tools.in`, kept apart so they never change the app's versions).
- The three files are generated by `backend/pin-requirements.sh` (pip-compile, Python 3.11, with the tools from
  `requirements-tools.txt` installed). Never edit them by hand. To add or change a dependency, edit
  `pyproject.toml` and run the script; `--upgrade` or `--upgrade-package <name>` moves versions. Commit the
  regenerated files with the change. CI fails if they are out of step.
- Dependabot (`.github/dependabot.yml`) opens grouped update PRs every Monday for pip, npm, GitHub Actions and the
  base images. Don't merge one with failing CI.

While working, run only the test files a change affects. Run both full suites once before each commit. The `web` and
`worker` images are built, not mounted: after a backend change, `./bmu down sim` and `./bmu up sim` to see it.

## Architecture

### Backend (`backend/bmu/`, FastAPI + DynamoDB + S3)

- **`app.py`** — the web app (`create_app()`; entry point `main.py`). All routes are `/api/*`; it also serves the
  built frontend for every other address. Sign-in takes the museum chosen (`tenant`, checked against the
  deployment's list; optional when it serves one); `/api/env` lists the museums for the sign-in page.
- **Roles** (design doc: "Roles") — every user has the CollectionSpace role BMU_Staff or BMU_Intern (named per tenant in `tenants/<key>.yaml` under `roles`; they carry no permissions). `app.py` refuses a sign-in with neither role, and a staff sign-in that lacks the tenant's `staff_permissions`. A session keeps its `role`. Endpoints take one of three dependencies: `current_session` (anyone signed in: viewing), `editor_session` (creates or changes a draft; `_intern_may` then limits an intern to drafts with `internOpen`), and `staff_session` (submit, schedule, queue, finished jobs), which reads the roles from CollectionSpace again on every request. A job keeps `createdBy`, `createdByRole` and `internOpen`. `POST /api/jobs/{id}/intern-access` changes `internOpen` (staff only; opening a draft to interns also clears its `review`). `POST …/review` is an intern's Submit for review: refused while a document needs fixing (not for `creator` documents), it makes the draft staff only and sets `review: {by, at}`, which Submit clears; the draft never enters the queue. In the editor it is the button at the bottom of the job, in place of Submit job, which an intern doesn't have. The frontend ids for it still read `hand-over-btn` (with `hand-over-confirm`, `hand-over-confirm-btn`, `hand-over-cancel-btn`) and `job-<id>-hand-over-btn` from "Hand over to staff", which it replaced; the mark is `job-<id>-review` and `review-note`. `POST …/to-drafts` moves a queued job to Drafts without opening it, and `POST …/schedule` also submits a draft nobody has open (Submit from the Drafts list). In the frontend, `lib/roles.ts` holds the same rules and the reasons shown on switched-off controls; components take a `staff` prop. Simulator users: `admin` and `limited` (staff), `intern`, and `newstaff` and `reader` (both refused at sign-in).
- **Three kinds of result** (design doc: "Roles") — a permission problem is never shown as a mistake in the job. A check's level is `block` (needs fixing), `creator` (the document needs a new Object and this user can't create Objects: `rows.needs_creator`, `rows.CREATOR`), `warn` or `info`; `rows.worst` ranks them in that order. `_recheck` counts `block`, `warn`, `creator` and `newObjects` (documents that will create an Object, whoever looks). `POST …/schedule` refuses a job with `creator` documents (409 `creator`): a job is submitted whole, by someone who can create its Objects, and there is deliberately no way to submit only the rest (it was built and removed on 5 October 2026, because the documents left out had nowhere to go once the job completed). Creating groups is the one other permission staff can lack after sign-in: `_account_problem` refuses Submit with 409 `account`, nothing is put on the documents, and the worker still checks it at the run (`permission_checks(..., run=True)`). For an intern, `_lookup_perms` assumes every permission except creating Objects (`proxy`), so nothing is held against the intern's own account. In the frontend: `lib/status.ts` (`NEEDS_CREATOR`, tone and theme colour `creator`, `CHECK_PREFIX`, `checksText`, `handlingNote`), `GROUP_PROBLEM` in `lib/roles.ts`, and ids `creator-note`, `show-creator-btn`, `group-account-problem`, `preview-needs-creator`. Don't add a permission check that marks a document "needs fixing".
- **The read-only service account** (`reader.py`; design doc: "Roles") — an intern's lookups (the draft checks, authority autocomplete, vocabularies, the date parser) go through `_lookup_client`, `_lookup_perms` and `_lookup_http` in `app.py`, which use the reader account when the session is an intern's and one is set up (`BMU_READER_SECRET_IDS` in AWS, one secret per museum; `BMU_READER_USER` and `BMU_READER_PASSWORD` locally, the simulator's `bmureader`; an AWS environment with the simulated CollectionSpace keeps `bmureader` in its secret, set by `./bmu aws deploy`). Every request it makes is counted against the intern (`reader_lookups_per_hour`, answer 429 `reader_limit`) and logged ("reader: <intern> made N lookups (<what>)"). If the account can't be used the answer is 503 `reader`, never a 401, so the intern stays signed in. Rows are stored in full; `minimal()` cuts every row in an answer to an intern (in the `csrf_guard` middleware) down to found or not and protected or not: no reason for protection, no access notes, no CSIDs. A new endpoint that reads CollectionSpace for a draft must use `_lookup_client`; a new row field that comes from an Object or Media record must be added to `_minimal_row`.

- **`worker.py`** — runs queued jobs (`python -m bmu.worker`): one `Worker` per museum, each in its own thread with
  its own connections (`main()`), one job at a time per museum, each document's steps in order, each step recording
  its CSID so a rerun runs only unfinished steps.
- **`rows.py`** — the checks on each document ("Must fix", "Warning"), used by the editor, by Submit and by the
  worker just before each document.
- **`schedule.py`** — run times, queue order, Run now, hold, pause.
- **`cspace/`** — the CollectionSpace client (`client.py`) and the XML payloads (`payloads.py`).
- **`storage.py`** — DynamoDB (jobs, rows, audit entries) and S3 (staged files, thumbnails).
- **`crypto.py`**, **`logsafe.py`** — credential encryption; keeping secrets out of logs.
- **`failures.yaml`** / **`failures.py`** — the failure catalog: every failure code with its title, explanation and
  what to do. A new failure code needs an entry here.
- **`sensitivity.py`**, **`thumbnails.py`**, **`filetypes.py`**, **`tenant.py`** + **`tenants/pahma.yaml`**.
- **`demo.py`** — the Demo tools' endpoints (`/api/_demo/*`), 404 unless `BMU_DEMO=true`.
- **`backend/fakecspace/`** — a simulated CollectionSpace for development and tests. It is not CollectionSpace:
  check real behaviour with `scripts/check_cspace.py` against the QA tenant.

Settings are environment variables prefixed `BMU_` (`config.py`, `.env.example`). The museums a deployment serves are
`BMU_TENANTS` (JSON, museum to CollectionSpace server; `Settings.museums()`), with `BMU_S3_KMS_KEY_IDS` and
`BMU_READER_SECRET_IDS` per museum in AWS; without them, `BMU_TENANT` on `BMU_CSPACE_URL` is the one museum.

### Frontend (`frontend/src/`, Vue 3 + TypeScript + Vuetify 3)

Built like the team's other apps (BOA, Damien, Diablo); `README.md`, Frontend, has the detail.

- **`views/`** — pages: `Login`, `BaseView` (app bar, tabs), `EditJob`, `Drafts`, `Queue`, `Finished`, `NotFound`.
  `Login` shows a museum list (`#museum`, options `museum-<key>`) when `/api/env` lists more than one museum, and
  remembers the choice in the browser (`bmu-museum`); the app bar shows the museum (`#tenant-name`).
- **`components/job/`** — the job screens; **`components/util/`** — shared pieces; **`components/demo/`** — Demo tools.
- **`stores/`** — Pinia: `context.ts` (current user, loading, screen-reader alerts), `job-edit-session.ts` (the job
  open in the editor, shared by the tabs).
- **`api/`** — axios calls to the BMU API; **`lib/`** — pure helpers (`table.ts`, `results.ts`, `status.ts`,
  `schedule.ts`, `files.ts`…); **`types.ts`** — shared types.
- **`router.ts`**, **`auth.ts`** — routes and their guards; **`plugins/vuetify.ts`** — themes and the list of
  registered Vuetify components (add a component there when first used).
- **`__tests__/`** — Vitest; `setup.ts` routes axios to a stubbed `fetch`, `app.ts` mounts the whole app.

### Frontend conventions

- `<template>` first, then `<script setup lang="ts">`, then `<style scoped>`. Props as a runtime `defineProps`
  object (`required`, `type`, `default`). Single quotes, no semicolons, one attribute per line when there are several.
- Every control has an `id`, built from the job's id or the document's number, not its position
  (`job-<id>-edit-btn`, `result-<n>`). State is readable from the page (chip text, `aria-expanded`, `aria-busy`).
  Browser tests will depend on these: don't rename an existing id without need.
- `v-html` is a lint error: text from CollectionSpace and from file names is only ever shown as text.
- Use axios only for the BMU API (it sends the `X-BMU` header by default); files go to S3 with their own request.
- In tables that can hold 100 rows, checkboxes and short lists are native elements (`.checkbox`, `.native-select`
  in `assets/styles/bmu-global.css`), and handlers are shared functions, not written inline per row.
- Nothing clickable is smaller than 24 pixels: no `size="x-small"` or `density="compact"` on a button (column
  headings set their own height). Keyboard focus is a solid outline, set in `bmu-global.css`.
- A list that loads from the server shows "Loading…" until the first answer, never its empty message.
- `npm audit` stays clean; don't add a package that breaks it.

### Tests

- Backend: pytest with moto (AWS) and the simulated CollectionSpace; `tests/test_flow.py` is the full path from
  sign-in to a finished run.
- Frontend: Vitest with `@vue/test-utils`. Find a job with `#job-<id>`, a job's line with `tr.job-row`.

## License

Copyright ©2026 The Regents of the University of California. `LICENSE` is the same license as UC Berkeley RTL's
other applications (BOA, Damien, Diablo): free to use, copy, modify and distribute for educational, research and
not-for-profit purposes; commercial use needs a license from UC Berkeley's Office of Technology Licensing.

- Don't change `LICENSE`'s text. The README's License section, `"license"` in `frontend/package.json` and `license`
  in `backend/pyproject.toml` all refer to it; keep them in step if it ever changes.
- Source files carry no license header; don't add one.
- Don't copy code into the repo from a source whose license is incompatible (GPL and the like). A new package must
  have a permissive license (MIT, BSD, Apache 2.0, ISC or similar).

## Documents kept in step with the code

- **UI mockup** — `docs/mockup/bmu-mockup.html` (plain HTML; the same layout and functions as the prototype, not
  the same look). A change to what a screen shows or does is made in both. This file is the only copy (there is no
  hosted copy to republish); UI review changes are made to it on a branch, like any other change.
- **Testing checklist** — `docs/testing-checklist.md`: the checks to do by hand. A pull request that needs checks
  by hand adds a section to it.
- **README.md** — what the prototype does, and the Frontend section.
- **Design document** — `docs/design.md` ("New BMU (uploadmedia): High-Level Architecture"). It is the only copy:
  the Claude document it came from holds just a pointer to this file. Change it in the same pull request as the
  code it describes, and add a dated line to its Status list (at the end of "Prototype plan") for a decision or a
  finished piece of work. Code comments that say "design:" name its sections.
- **Background notes** — `docs/background/`: notes on CollectionSpace and comparisons with it, such as
  `type-ahead-comparison.md`. They describe; the design document decides.
- Update the mockup and the documents once per pull request, not alongside each change.
