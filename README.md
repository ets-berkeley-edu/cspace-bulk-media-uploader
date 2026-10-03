# New CollectionSpace Bulk Media Uploader (prototype)

A prototype of the new Bulk Media Uploader (BMU) for UC Berkeley's CollectionSpace tenants, replacing the
legacy `uploadmedia` Django webapp in `cspace-webapps-common`. It follows the design document
"New BMU (uploadmedia): High-Level Architecture" and its UI mockup.

It implements the design for **PAHMA**. Not built yet: the other tenants, the TIFF quality checks, the audit-log
screen (the audit entries are written), the Restricted Media option and tuning for 1,000-document jobs. The AWS
deployment is built (`deploy/README.md`); what it leaves for later is listed there.

## What it does

- **Sign in** with your CollectionSpace account (HTTP Basic). The BMU reads your permissions
  (`accounts/0/accountperms`) and roles (`accounts/0/accountroles`). Creating or editing jobs needs create and
  update on Media records; without them you can only view jobs.
- **Create a job and add files.** The browser uploads each file straight to S3 with a presigned POST (with Retry
  and Remove if an upload fails), reads its EXIF date and orientation, and shows a thumbnail. Accepted: JPEG, TIFF,
  PNG, PDF, WAV, MP3, AAC, MP4 and X3D; other files are skipped with a message. Filenames follow PAHMA's rule: the
  object number, optionally followed by `_` and anything else (`15-1234_a.jpg`, `1-2345_01_b.tif`); a name can be
  corrected in the editor.
- **Edit each document:** its handling (Link to existing object, Link to object (create if missing), Create new
  object + link, Media only (no object)), Restricted, identification number, date (parsed by CollectionSpace's own
  date parser), media types and languages (repeating), creator, contributor and rights holder (autocomplete of
  existing authority terms; values are refNames), description and copyright. The side panel applies changes to
  the selected documents or to all. Handling options can carry presets (PAHMA has none configured). Documents can
  be excluded from a job, or deleted if they created nothing in CollectionSpace. Large jobs are paged, sorted and
  filtered.
- **Groups:** "Create a group of this job's objects" creates one CollectionSpace Group, with the Group title you give it, and adds every linked Object to it.
  Its title is typed, or filled with **Use the job name** or **Use a timestamp** (`bmu-YYYY-MM-DD-HH-MM-SS`).
- **Checks while editing:** each document is checked against CollectionSpace when its file is added and whenever
  it changes, with the results on the row as "Must fix", "Warning" or information: the object found and not
  ambiguous (or not existing, for Create new object + link), permissions (including read permissions each check
  needs), duplicate identification numbers, file type, the date, and that each authority term, language and media
  type still exists (a renamed term is updated to its current name). Protected files (Objects the tenant's rules
  mark sensitive) get no stored thumbnail and a "don't publish" default; the Public portal column shows what the
  public will see.
- **Drafts:** every change is saved as it's made. Anyone in the tenant can open a draft, one person at a time,
  with take-over. Drafts expire 30 days after they were last saved (7 if a document is a protected file).
- **Submit job** (only when nothing needs fixing) checks the whole job again with fresh permissions and adds it
  to the end of the job queue, with the submitter's password saved encrypted for at most 72 hours.
- **Job scheduling:** queued jobs start at the tenant's run times (by default every day at 7:00 PM Pacific), one
  job at a time per tenant, in queue order. Users with the CollectionSpace role **BMU_Scheduler**
  (`ROLE_<tenant id>_BMU_SCHEDULER`) can change the run days and times, pause and resume the queue, reorder it,
  and give a job Run now, its own run time or a hold. Everyone sees when each job will run. Cancel run is for
  schedulers and the person who submitted the job. A job whose saved sign-in expires while it waits moves back to
  Drafts.
- **The run:** a worker runs each document's steps in order: check the document in CollectionSpace again, create
  the Media record, find or create the Object, attach the file (`PUT media/{csid}/blob`, which creates the Blob),
  relate Media and Object both ways, and add the Object to the job's Group. Before the first document, and again
  just before each one, the worker checks that its terms, languages and media types still exist: a renamed term
  is used under its current name (with a notice); a document whose value no longer exists fails before anything
  is created for it. The same check, just before each document, covers everything else the editor checked: the
  account's permissions, the Object the handling needs (missing, already there for "Create new object + link", or
  matching several) and the staged file. A document that fails it has nothing created, so a change in
  CollectionSpace between submitting and running doesn't leave a Media record without its Object. Each step records its CSID; a step whose dependencies failed is skipped. A rerun runs only
  unfinished steps. Five failed requests in a row, or a refused sign-in, stop the job.
- **Finished jobs:** each job's outcome (Completed, Needs attention, Failed), documents by result and run history.
  View results shows every document's steps and CSIDs, and every failure in plain language (title, explanation,
  what to do, technical detail) from the failure catalog in `backend/bmu/failures.yaml`. **Fix and reschedule**
  (or **Reschedule**, when every failure only needs another run) moves the job to Drafts; a fix that isn't
  submitted within 30 days (7 if a document is a protected file) is reverted. Jobs that need attention or failed can be deleted from the BMU (never from
  CollectionSpace: the BMU only creates records). Completed jobs are removed 30 days after they finish.
- **Credentials:** the password is encrypted at rest (a session key while you're signed in, a separate job key
  while a job waits or runs) and deleted when the run ends, whatever the outcome.

## Layout

| Path | What |
| --- | --- |
| `backend/bmu/` | FastAPI app (`app.py`), worker (`worker.py`), row checks (`rows.py`), job scheduling (`schedule.py`), CollectionSpace client and payloads (`cspace/`), storage (DynamoDB, S3), credential encryption |
| `backend/bmu/tenants/pahma.yaml` | PAHMA configuration: handling options, filename rule, field lists, sensitivity rules, scheduler roles |
| `backend/bmu/failures.yaml` | The failure catalog: every failure code with its title, explanation and what to do |
| `backend/fakecspace/` | A simulated CollectionSpace API for development and tests (not CollectionSpace) |
| `backend/tests/` | pytest: unit tests and the full run path with moto (AWS) and the simulated CollectionSpace |
| `frontend/` | Vue 3 + TypeScript app (Vite, Vitest) |
| `scripts/check_cspace.py` | Checks the BMU's calls against a real CollectionSpace server |
| `scripts/find_csid.py` | Finds which BMU job created a CollectionSpace record |
| `docker-compose.yml` | Local stack: web, worker, Vue dev server, DynamoDB Local, moto (S3), simulated CollectionSpace |
| `bmu` | Starts, stops and opens the environments (below), and deploys to AWS (`./bmu aws`) |
| `deploy/` | The AWS deployment: production image (`Dockerfile`), Terraform (`terraform/`), per-account settings (`environments/`) and `aws.sh`; see [deploy/README.md](deploy/README.md) |

## Run it locally

Requires Docker.

```sh
cp .env.example .env
# put two random keys in .env (BMU_SESSION_KEY_B64 and BMU_JOB_KEY_B64):
python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
docker compose up --build
```

Open http://localhost:5173. With the simulated CollectionSpace, sign in as:

| User | Permissions |
| --- | --- |
| `admin` / `admin` | Everything, and the BMU_Scheduler role |
| `limited` / `limited` | Can't create objects or groups; not a scheduler |
| `reader` / `reader` | Read only: can view jobs but not create or edit them |

Submitted jobs wait for the run time (7:00 PM Pacific). To have them start at once while you try things, set
`BMU_ALWAYS_RUN_TIME=true` in `.env` (or start with `BMU_ALWAYS_RUN_TIME=true docker compose up`); pause and hold
still apply. Without it, sign in as `admin` and use **Run now** in the Job queue.

Sample objects (list them with `curl localhost:8180/_fake/objects`):

| Object number | For testing |
| --- | --- |
| `15-1234`, `12-5678`, `15-1240`, `1-2345`, `3-1001`, `3-1002`, `16-4711` | Ordinary objects (a Media record with ID `15-1234` already exists) |
| `3-1003.1` | A part number with a dot, e.g. `3-1003.1_a.jpg` |
| `9-9999` | Two objects share this number |
| `3-1004` | Deleted in CollectionSpace, so searches don't find it |
| `12-2001` | Sensitive: culturally sensitive, Human Remains department |
| `12-2002` | Sensitive: NAGPRA status and a display restriction at the "restriction" level |
| `12-2003` | Not sensitive, but a display restriction at the "preference" level (a warning) |

Documents linked to `12-2001` or `12-2002` become protected files automatically; `12-2003` gives a warning.
The rules are in `backend/bmu/tenants/pahma.yaml` (`sensitivity`), and the Object field names they read must be
confirmed on the QA tenant with `scripts/check_cspace.py --object <number> --show-object`.

The sample Persons are Madeleine W. Fang, Leslie Freund, Natasha Johnson, Michael T. Black, Linda Waterfield and
Zachary Williams; the sample Organizations are the Phoebe A. Hearst Museum of Anthropology and the University of
California at Berkeley Regents. The languages are English, Spanish, French, German, Chinese, Japanese, Hawaiian
and Navajo (codes `eng`, `spa`, `fre`, `ger`, `chi`, `jpn`, `haw`, `nav`).

The simulator's state is at http://localhost:8180/_fake/state; reset it with `curl -X POST localhost:8180/_fake/reset`.

### Demo tools (demo builds only)

The local stack shows a **Demo tools** pane under the sign-in bar. It collapses to one line (the triangle at its left),
and your browser remembers that. From it you can:

- slow the file transfers: the browser's uploads in Create / edit job (e.g. 1 MB/s), and in job runs, the file uploads
  to CollectionSpace and an added delay per create;
- make the simulated CollectionSpace fail at a step, with a status, a number of times, for matching documents;
- delete, "merge away" (404) or rename a sample Person or Organization, and remove or rename a language;
- reset the simulator, put browser uploads back to full speed, and delete every job in the tenant (except running
  ones) to start a demo afresh;
- see the simulator's sample objects, and copy the commands for the check scripts, the simulator and the tests.

It is off everywhere else, twice over. The pane is only in demo builds: `npm run dev` and `npm run build:demo` include
it, `npm run build` (production) leaves its code out of the bundle. Its server endpoints (`/api/_demo/...`) answer 404
unless the web app runs with `BMU_DEMO=true`, which `docker-compose.yml` sets for the local stack only. They need a
signed-in user. Nothing in them is part of the BMU's design: they drive the simulator's `/_fake` controls below, and
slow a browser upload by sending the presigned form through the web app, which passes it on to S3 at the set speed.
Use large sample files (50 MB or more) to watch a slowed upload: the first few MB fill network buffers at once.

### Changing things in the simulated CollectionSpace

To watch the job queue, or to cancel a run partway, slow the simulated CollectionSpace down so each create and
upload takes a while: `curl -X POST 'localhost:8180/_fake/slow?seconds=2'` (`seconds=0` turns it off). Add
`upload_mbps` to also receive files slowly, so the running job's upload bar ("Now: …, uploading the file" with
the share and MB sent) can be watched with large files: `curl -X POST 'localhost:8180/_fake/slow?seconds=1&upload_mbps=10'`.
To slow the uploads in Create / edit job instead (the browser sends those straight to S3), use Demo tools, or your
browser's network throttling (Chrome DevTools → Network).

To see how the BMU handles terms and languages that change after a document was filled in:

```sh
curl -X POST 'localhost:8180/_fake/delete-term?name=Natasha%20Johnson'              # soft-deleted (how=gone: not found)
curl -X POST 'localhost:8180/_fake/rename-term?name=Leslie%20Freund&to=Leslie%20F.%20Freund'
curl -X POST 'localhost:8180/_fake/delete-language?code=spa'                         # leaves the language list
curl -X POST 'localhost:8180/_fake/rename-language?code=spa&to=Espa%C3%B1ol'
```

A draft shows a deleted term as "Must fix" and takes a renamed one's current name. A queued job's preview says so
too; when the job runs, a document with a deleted value fails before anything is created (`value_missing`), and
one with a renamed term is sent with the current name (notice `term_renamed`).

To see how the BMU reports failures, make the simulated CollectionSpace fail on purpose. Rules apply only to
job runs (not to the editor's checks) and are used up after one matching request unless you pass `count=0`:

```sh
curl -X POST 'localhost:8180/_fake/fail?step=upload&status=413&match=1-2345'         # file too large
curl -X POST 'localhost:8180/_fake/fail?step=objectSearch&effect=none&match=15-1234'  # object gone at run time
curl -X POST 'localhost:8180/_fake/fail?step=objectSearch&effect=many&match=15-1240'  # several objects
curl -X POST 'localhost:8180/_fake/fail?step=media&status=400&match=12-5678'          # Media record rejected
curl -X POST 'localhost:8180/_fake/fail?step=relation&status=403&count=0'             # no permission for relations
curl -X POST 'localhost:8180/_fake/fail?step=media&status=401'                        # sign-in failed (job stops)
curl -X POST 'localhost:8180/_fake/fail?step=media&status=503&count=0'                # outage: 5 in a row stop the job
curl -X POST 'localhost:8180/_fake/fail?step=mediaSearch&effect=many'                 # ID in use since submission (notice)
curl -X POST 'localhost:8180/_fake/fail?step=group&status=400'                        # the job's group can't be created
curl -X POST 'localhost:8180/_fake/fail?step=termRead&status=503&match=7475'          # a term can't be read at run time
curl localhost:8180/_fake/fail            # list the rules
curl -X DELETE localhost:8180/_fake/fail  # clear them
```

`match` is compared with the document's identification number, filename, object number and group title (for
`termRead`, the term's short identifier or display name). Steps: `media`, `upload`, `objectSearch`,
`objectCreate`, `relation`, `mediaSearch`, `group`, `termRead`. Add `client=any` to make a rule apply to the
editor's checks as well.

To use the Lyrasis QA tenant instead, start `./bmu up qa` (see Several environments below), or set
`BMU_CSPACE_URL=https://pahma.qa.collectionspace.org` in `.env`, and sign in with a QA account. Records created there
stay (the BMU never deletes).

## Several environments: simulator, PAHMA QA, AWS, and the UI mockup

`./bmu` starts, stops and opens each environment. The two local ones can run at the same time: each is its own Docker
Compose project with its own ports, data, session cookie and label, shown on the sign-in page, in the header and in
the browser tab's title (orange when the CollectionSpace is a real server).

| Command | What | Address |
| --- | --- | --- |
| `./bmu up sim` | Local, simulated CollectionSpace, Demo tools on (sign in as `admin` / `admin`) | http://localhost:5173 |
| `./bmu up qa` | Local, against the PAHMA QA tenant, with your own QA account. **Jobs create real records, which stay.** Demo tools off | http://localhost:5273 |
| `./bmu aws deploy` | Deploys to AWS (default: Richard's personal account, against the PAHMA QA tenant; real records). See [deploy/README.md](deploy/README.md) | `https://….cloudfront.net` |
| `./bmu open aws` | The AWS deployment, at the address `./bmu aws deploy` saved (or `BMU_AWS_DEV_URL`) | — |
| `./bmu open mockup` | The UI mockup, from this repo (`docs/mockup/bmu-mockup.html`); `./bmu open mockup-hosted` opens the hosted copy | — |
| `./bmu open home` | A start page linking all of them (`docs/start.html`) | — |

Also `./bmu status`, `./bmu logs sim|qa [service]`, `./bmu down sim|qa|all` and `./bmu urls`. Both local environments
use the keys in `.env`; neither stores a password (`BMU_QA_CSPACE_URL` points the QA one at another server).
Plain `docker compose up` still starts the simulator environment as before; the ports, label and cookie name are
variables in `docker-compose.yml` (`BMU_UI_PORT`, `BMU_API_PORT`, `BMU_S3_PORT`, `BMU_DYNAMODB_PORT`, `BMU_SIM_PORT`,
`BMU_ENV_LABEL`, `BMU_COOKIE_NAME`) with the simulator's values as defaults.

The UI mockup in `docs/mockup/` is no longer updated: it shows the design as of September 30, 2026, and is being
retired. The prototype is the reference for how the BMU looks and behaves.

## Development without Docker

```sh
cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]' && pytest
cd frontend && npm ci && npm test && npm run typecheck && npm run build
```

## Checking against the real CollectionSpace

The CollectionSpace calls in `backend/bmu/cspace/client.py` were checked against the PAHMA QA tenant. To
recheck them (for example against another tenant), run the check script from a machine that can reach the
server. It is read-only unless you pass `--create`.

```sh
pip install -e backend
export CSPACE_URL=https://pahma.qa.collectionspace.org CSPACE_USER=... CSPACE_PASSWORD=...
python scripts/check_cspace.py --object <an existing object number> --term <3+ letters of a person's name>
python scripts/check_cspace.py --object <number> --show-object   # the Object's fields and the sensitivity verdict
python scripts/check_cspace.py --vocabularies                    # the Person and Organization vocabularies
python scripts/check_cspace.py --roles                           # your roles, and whether you're a BMU scheduler
python scripts/check_cspace.py --terms person:<short id> ...     # read terms as the BMU does (deleted, merged, renamed)
python scripts/check_cspace.py --create                          # also creates one test Media/Object pair (BMU-TEST-<time>)
```

## Security notes

- Passwords are never stored in plain text or logged. The session cookie is httpOnly and SameSite=Strict,
  and state-changing API calls also require an `X-BMU: 1` header.
- In AWS, set `BMU_CRYPTO_MODE=kms` with separate KMS keys for sessions and jobs
  (`BMU_KMS_SESSION_KEY_ID`, `BMU_KMS_JOB_KEY_ID`); the local mode uses keys from the environment. The
  Terraform code (`deploy/terraform/`) sets these, with key policies that let only the web app use the session key and
  only the worker decrypt with the job key.
- File uploads go directly from the browser to S3 with a write-only presigned POST for one key
  (`staging/<tenant>/<job>/<row>/<random>`), the file's size (at most 2 GB for now) and content type, for
  15 minutes; set `BMU_S3_KMS_KEY_ID` in AWS to require SSE-KMS. The worker checks each file's real type from its
  first bytes before streaming it to CollectionSpace. A staged file is deleted as soon as its upload to
  CollectionSpace succeeds; a protected file's staged upload is also removed 7 days after its job stopped. No
  presigned download URLs are given to anyone; thumbnails are served by the web app after checking the session.
- Sessions end after 30 minutes without activity (`BMU_SESSION_IDLE_MINUTES`) or 8 hours in all
  (`BMU_SESSION_HOURS`); the lists' background refreshes don't count as activity.
- Schedule and queue changes check the BMU_Scheduler role on the server each time, so removing the role takes
  effect at once.

## Audit log

The audit table records, with who and when: every run (each document's filename, object number, CSIDs and error
codes, in S3 under `audit/` for runs over 100 documents), submitted jobs, moves to Drafts, take-overs, jobs
becoming Completed, row and job deletions, expired and reverted drafts, expired Completed jobs, expired sign-ins,
removed protected uploads, and every schedule and queue change (schedule changed, queue paused or resumed, Run
now, run time set or cleared, job held or released, queue reordered, run cancelled). A finished run and its audit
entry are written together, and the run keeps the entry's key. Each record the BMU creates is also indexed by its
CSID, so you can find which job made it, even after the job is deleted:

```sh
cd backend && python ../scripts/find_csid.py <csid>
```

## License

Educational Community License, Version 2.0 (ECL-2.0), the license CollectionSpace uses. See `LICENSE`.
