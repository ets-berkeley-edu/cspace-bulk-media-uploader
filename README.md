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
- Check against CollectionSpace (object found, not ambiguous, permissions, duplicate IDs) and Schedule.
- A worker runs the job one row at a time, following the design's steps: create the Media record, find (or
  create the skeletal) Object, attach the file with a multipart `PUT media/{csid}/blob` (CollectionSpace
  creates the Blob record and sets `blobCsid`), and relate Media and Object both ways. Each step records its
  CSID; a step whose dependencies failed is skipped. A rerun (Reschedule) runs only unfinished steps,
  retries an upload against the existing Media record, and checks for existing Relations first.
- Credentials: the password is encrypted at rest (a session key while signed in, a separate job key while a
  job waits or runs, for at most 72 hours) and deleted when the run ends, whatever the outcome.
- One job per tenant at a time (a lock with a heartbeat), and an audit entry for each run.

Deferred to later iterations: drafts with locking and take-over, queue reordering and Cancel run, Fix and
reschedule with row edits, Groups, automatic protected files and the Public portal column, the Botanical
Garden initials pane, the other four tenants, the audit-log UI, 1,000-row tuning, Restricted Media and
server-side TIFF thumbnails.

## Layout

| Path | What |
| --- | --- |
| `backend/bmu/` | FastAPI app (`app.py`), worker (`worker.py`), CollectionSpace client and payloads (`cspace/`), storage (DynamoDB, S3), credential encryption, row checks |
| `backend/bmu/tenants/pahma.yaml` | PAHMA configuration carried over from the legacy `uploadmedia.cfg` |
| `backend/fakecspace/` | A simulated CollectionSpace API for development and tests (not CollectionSpace) |
| `backend/tests/` | pytest: unit tests and the full run path with moto (AWS) and the simulated CollectionSpace |
| `frontend/` | Vue 3 + TypeScript app (Vite, Vitest) |
| `scripts/check_cspace.py` | Checks the BMU's calls against a real CollectionSpace server |
| `docker-compose.yml` | Local stack: web, worker, Vue dev server, DynamoDB Local, MinIO, simulated CollectionSpace |

## Run it locally

Requires Docker.

```sh
cp .env.example .env
# put two random keys in .env:
python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
docker compose up --build
```

Open http://localhost:5173. With the simulated CollectionSpace, sign in as `admin`/`admin` (all permissions),
`limited`/`limited` (can't create objects) or `reader`/`reader` (read only). Objects `15-1234`, `12-5678`,
`15-1240` and `1-2345` exist; `9-9999` matches two objects. The simulator's state is at
http://localhost:8180/_fake/state.

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
