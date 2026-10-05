# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A prototype of the new Bulk Media Uploader (BMU) for UC Berkeley's CollectionSpace tenants, replacing the legacy
`uploadmedia` Django webapp. Museum staff sign in with their own CollectionSpace account, add media files to a job,
edit each document, and submit the job; a worker later creates the Media record, the Blob, the Object (when asked)
and the Relations in CollectionSpace. It implements the design for PAHMA. `README.md` describes what it does and how
to run it; `deploy/README.md` covers AWS.

## Rules that are not negotiable

- **The BMU is create-only.** It never deletes or cleans up anything in CollectionSpace. Deleting a job or a document
  removes it from the BMU only.
- **Credentials are the user's own**, HTTP Basic only. A password is never stored permanently: it is encrypted at
  rest (session key while signed in, job key while a job waits or runs) and deleted when the run ends.
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
# Backend (Python 3.11+, FastAPI)
cd backend && pip install -e '.[dev]'
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

CI (`.github/workflows/ci.yml`) runs `pytest -q`, then `npm run lint`, `typecheck`, `test` and `build`.

While working, run only the test files a change affects. Run both full suites once before each commit. The `web` and
`worker` images are built, not mounted: after a backend change, `./bmu down sim` and `./bmu up sim` to see it.

## Architecture

### Backend (`backend/bmu/`, FastAPI + DynamoDB + S3)

- **`app.py`** — the web app (`create_app()`; entry point `main.py`). All routes are `/api/*`; it also serves the
  built frontend for every other address.
- **Roles** (design doc: "Roles") — every user has the CollectionSpace role BMU_Staff or BMU_Intern (named per tenant in `tenants/<key>.yaml` under `roles`; they carry no permissions). `app.py` refuses a sign-in with neither role, and a staff sign-in that lacks the tenant's `staff_permissions`. A session keeps its `role`. Endpoints take one of three dependencies: `current_session` (anyone signed in: viewing), `editor_session` (creates or changes a draft; `_intern_may` then limits an intern to drafts with `internOpen`), and `staff_session` (submit, schedule, queue, finished jobs), which reads the roles from CollectionSpace again on every request. A job keeps `createdBy`, `createdByRole` and `internOpen`. In the frontend, `lib/roles.ts` holds the same rules and the reasons shown on switched-off controls; components take a `staff` prop. Simulator users: `admin` and `limited` (staff), `intern`, and `newstaff` and `reader` (both refused at sign-in).

- **`worker.py`** — runs queued jobs (`python -m bmu.worker`): one job at a time per tenant, each document's steps
  in order, each step recording its CSID so a rerun runs only unfinished steps.
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

Settings are environment variables prefixed `BMU_` (`config.py`, `.env.example`).

### Frontend (`frontend/src/`, Vue 3 + TypeScript + Vuetify 3)

Built like the team's other apps (BOA, Damien, Diablo); `README.md`, Frontend, has the detail.

- **`views/`** — pages: `Login`, `BaseView` (app bar, tabs), `EditJob`, `Drafts`, `Queue`, `Finished`, `NotFound`.
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

## Documents kept in step with the code

- **UI mockup** — `docs/mockup/bmu-mockup.html` (plain HTML; the same layout and functions as the prototype, not
  the same look). A change to what a screen shows or does is made in both.
- **README.md** — what the prototype does, and the Frontend section.
- The design document ("New BMU (uploadmedia): High-Level Architecture") is kept outside the repo; update the
  mockup and the documents once per pull request, not alongside each change.
