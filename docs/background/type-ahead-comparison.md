# Authority type-ahead: the BMU compared with CollectionSpace

Background note, October 6, 2026, checked against `main` at commit `3354666`. It compares the BMU's autocomplete
for authority fields (Creator, Contributor, Rights holder) with the CollectionSpace UI's. The design itself is in
`docs/design.md`, "Authority term fields"; this note doesn't change it.

## Sources

- In this repo: `README.md`, `docs/design.md` ("Authority term fields"), `backend/bmu/app.py` (`/api/authorities`),
  `backend/bmu/cspace/client.py` (`search_terms_page`, `authority_term_state`), `backend/bmu/tenants/pahma.yaml`
  and `frontend/src/components/util/AuthorityInput.vue`.
- `cspace-ui.js` itself was not re-read. The CollectionSpace UI's behavior comes from `docs/design.md`, which follows
  the UCB fork of cspace-ui.js (10.2.0-ucb.1), and from earlier notes kept outside this repo.

## How the BMU works

- `AuthorityInput.vue` waits for the tenant's minimum length and find delay, then calls the BMU web app at
  `GET /api/authorities?field=...&q=...`.
- The web app sends one request per configured source to CollectionSpace:
  `GET <service>/urn:cspace:name(<vocab>)/items?pt=<text>&wf_deleted=false&pgSz=20`. This is the same partial-term
  query the CollectionSpace UI uses. The browser never talks to CollectionSpace directly.
- The stored value is the chosen term's refName. Typed text that wasn't picked from the list reverts on blur.

## Where the BMU matches the CollectionSpace UI

- Search rule: 3+ characters, then a pause. The values come from the tenant's UI profile. PAHMA uses 3 characters
  and 1,000 ms; cspace-ui's defaults are 3 characters and 500 ms. The server also enforces the minimum length.
- Deleted terms are excluded (`wf_deleted=false`).
- Results are grouped by source. The BMU's headings are "Persons" and "Organizations", not the UI's source names.
- Only the first page of results is fetched (20 per source), with a match count. The BMU also shows a "continue
  typing to narrow" hint.
- Sources the user can't read are dropped. If every source is dropped, the BMU shows a message where the UI shows
  nothing.
- PAHMA's sources are local Person and Organization only, because PAHMA configures no shared vocabulary (confirmed
  on QA, September 29).

## Deliberate or noted differences

- **No Quick Add.** The BMU never creates authority terms. New terms are added in CollectionSpace first, so the BMU
  needs no create permission on authorities.
- **Alternate (non-preferred) terms.** The UI shows them indented under the main term. The BMU shows only
  `termDisplayName`. No handling found.
- **Deprecated terms.** The UI shows them grayed out. The BMU doesn't distinguish them. No handling found.

## Where the BMU goes further

- Picked values are checked again later. The editor looks each refName up by its short identifier. A deleted or
  merged term blocks the row. A renamed term is updated to its current refName, with a note. The worker repeats this
  check at the start of a run and before each document (failure code `value_missing`).
- Presets, the side panel and creator-initials mappings all fill in full refNames.
- Interns' searches use a separate read-only service account, rate-limited and logged, because interns have no
  CollectionSpace permissions of their own.

## Compared with the earlier single-file sample uploader (deleted)

- The sample downloaded every term once and filtered it in the browser with a `<datalist>`. That needed a short
  fixed list of authority instances and had a cap on the number of terms.
- The BMU searches the full authority on the server with `pt=`, which was the fix suggested at the time.

## Open items

- Decide whether PAHMA needs alternate-term matching or deprecated-term styling. If PAHMA uses non-preferred terms,
  a search that matches only an alternate name would show the preferred name with no explanation.
- The design calls for a build step that takes each tenant's autocomplete sources and timing from its actual
  cspace-ui profile. The prototype doesn't have it yet: `pahma.yaml` is written by hand, and nothing checks it
  against the running UI.

This note contains no passwords, tokens, keys, account names or personal details.
