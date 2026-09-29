# New CollectionSpace Bulk Media Uploader (prototype)

A prototype of the new Bulk Media Uploader (BMU) for UC Berkeley's CollectionSpace tenants, replacing the
legacy `uploadmedia` Django webapp in `cspace-webapps-common`. It follows the design document
"New BMU (uploadmedia): High-Level Architecture" and its UI mockup.

This first iteration covers the **core run path for PAHMA**:

- Sign in with your CollectionSpace account (HTTP Basic, checked against `accounts/0/accountperms`).
- Create a job, drop files. The browser uploads each file straight to S3 with a presigned POST, reads its
  EXIF date and shows a local preview.
- Edit each document's handling (link to an existing object, create a new object and link, or media only),
  Restricted, identification number, date, media type, creator/contributor/rights holder (autocomplete of
  existing authority terms; values are refNames), description and copyright.
- Checks while editing, as in the design: each document is checked against CollectionSpace when its file is
  added and whenever it changes (object found and not ambiguous, permissions, duplicate IDs, file type, date),
  with the results on the row as "Must fix" or "Warning". Schedule job stays disabled until nothing needs
  fixing, then fetches permissions again and re-checks the whole job.
- A worker runs the job one row at a time, following the design's steps: create the Media record, find (or
  create the skeletal) Object, attach the file with a multipart `PUT media/{csid}/blob` (CollectionSpace
  creates the Blob record and sets `blobCsid`), and relate Media and Object both ways. Each step records its
  CSID; a step whose dependencies failed is skipped. A rerun runs only unfinished steps, retries an upload
  against the existing Media record, and checks for existing Relations first.
- Finished jobs: each job's outcome (Completed, Needs attention, Failed), documents by result and its run
  history. View results shows every document's steps, CSIDs and the run that did each, and every failure in
  plain language (title, explanation, what to do, technical detail on request) from the failure catalog in
  `backend/bmu/failures.yaml`. Fix and reschedule (or Reschedule, when every failure only needs another run)
  moves the job to Drafts: done documents are read-only, a document whose Media record exists takes only what
  the rerun needs (a corrected object number, stopping the link to an object, a replacement file), and a fix
  not scheduled within 30 days is reverted. Jobs that need attention or failed can be deleted from the BMU
  (never from CollectionSpace); Completed jobs are removed 30 days after they finish.
- Credentials: the password is encrypted at rest (a session key while signed in, a separate job key while a
  job waits or runs, for at most 72 hours) and deleted when the run ends, whatever the outcome.
- One job per tenant at a time (a lock with a heartbeat), and an audit entry for each run.

The goal is the full design document and UI mockup; this is the first part of it.

## Layout

| Path | What |
| --- | --- |
| `backend/bmu/` | FastAPI app (`app.py`), worker (`worker.py`), CollectionSpace client and payloads (`cspace/`), storage (DynamoDB, S3), credential encryption, row checks |
| `backend/bmu/tenants/pahma.yaml` | PAHMA configuration carried over from the legacy `uploadmedia.cfg` |
| `backend/fakecspace/` | A simulated CollectionSpace API for development and tests (not CollectionSpace) |
| `backend/tests/` | pytest: unit tests and the full run path with moto (AWS) and the simulated CollectionSpace |
| `frontend/` | Vue 3 + TypeScript app (Vite, Vitest) |
| `scripts/check_cspace.py` | Checks the BMU's calls against a real CollectionSpace server |
| `docker-compose.yml` | Local stack: web, worker, Vue dev server, DynamoDB Local, moto (S3), simulated CollectionSpace |

## Run it locally

Requires Docker.

```sh
cp .env.example .env
# put two random keys in .env:
python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
docker compose up --build
```

Open http://localhost:5173. With the simulated CollectionSpace, sign in as `admin`/`admin` (all permissions),
`limited`/`limited` (can't create objects or groups) or `reader`/`reader` (read only). Sample objects (list them with
`curl localhost:8180/_fake/objects`):

| Object number | For testing |
| --- | --- |
| `15-1234`, `12-5678`, `15-1240`, `1-2345`, `3-1001`, `3-1002`, `16-4711` | Ordinary objects (a Media record with ID `15-1234` already exists) |
| `3-1003.1` | A part number with a dot, e.g. `3-1003.1_a.jpg` |
| `9-9999` | Two objects share this number |
| `3-1004` | Deleted in CollectionSpace, so searches don't find it |
| `12-2001` | Sensitive: culturally sensitive, Human Remains department |
| `12-2002` | Sensitive: NAGPRA status and a display restriction at the "restriction" level |
| `12-2003` | Not sensitive, but a display restriction at the "preference" level (a warning in the design) |

Documents linked to `12-2001` or `12-2002` become protected files automatically; `12-2003` gives a warning.
The rules are in `backend/bmu/tenants/pahma.yaml` (`sensitivity`), and the Object field names they read must be
confirmed on the QA tenant with `scripts/check_cspace.py --object <number> --show-object`. The simulator's state is at http://localhost:8180/_fake/state (reset it with
`curl -X POST localhost:8180/_fake/reset`).

To watch the job queue, or to cancel a run partway, slow the simulated CollectionSpace down so each create and
upload takes a while: `curl -X POST 'localhost:8180/_fake/slow?seconds=2'` (`seconds=0` turns it off).

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
curl -X POST 'localhost:8180/_fake/fail?step=mediaSearch&effect=many'                 # ID in use since scheduling (notice)
curl -X POST 'localhost:8180/_fake/fail?step=group&status=400'                        # the job's group can't be created
curl localhost:8180/_fake/fail            # list the rules
curl -X DELETE localhost:8180/_fake/fail  # clear them
```

`match` is compared with the document's identification number, filename and object number. Steps: `media`,
`upload`, `objectSearch`, `objectCreate`, `relation`, `mediaSearch`, `group`.

To use the Lyrasis QA tenant instead, set `BMU_CSPACE_URL=https://pahma.qa.collectionspace.org` in `.env`
and sign in with a QA account. Records created there stay (the BMU never deletes).

## Development without Docker

```sh
cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]' && pytest
cd frontend && npm ci && npm test && npm run typecheck && npm run build
```

## Checking against the real CollectionSpace

The CollectionSpace calls in `backend/bmu/cspace/client.py` were checked against the PAHMA QA tenant. To
recheck them (for example against another tenant), run the check script from a machine that can reach the server:

```sh
pip install -e backend
export CSPACE_URL=https://pahma.qa.collectionspace.org CSPACE_USER=... CSPACE_PASSWORD=...
python scripts/check_cspace.py --object <an existing object number> --term <3+ letters of a person's name>
python scripts/check_cspace.py --create    # also creates one test Media/Object pair (BMU-TEST-<time>)
```

## Security notes

- Passwords are never stored in plain text or logged. The session cookie is httpOnly and SameSite=Strict,
  and state-changing API calls also require an `X-BMU: 1` header.
- In AWS, set `BMU_CRYPTO_MODE=kms` with separate KMS keys for sessions and jobs
  (`BMU_KMS_SESSION_KEY_ID`, `BMU_KMS_JOB_KEY_ID`); the local mode uses keys from the environment.
- File uploads go directly from the browser to S3; the worker streams them to CollectionSpace. No presigned
  download URLs are given to anyone.

## License

Educational Community License, Version 2.0 (ECL-2.0), the license CollectionSpace uses. See `LICENSE`.
