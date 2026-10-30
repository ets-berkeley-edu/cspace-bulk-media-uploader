# bmut: the BMU's Selenium tests

Browser checks of the BMU on a local stack with the simulated CollectionSpace, written as the team writes them for
BOA (bea), Damien (mrsbaylock), Diablo (xena) and Serena (serenade): pytest, with a page object per screen in
`pages/` and the tests in `tests/`. They run only against the local test stack, never QA, AWS or production: they
sign in with the simulator's synthetic accounts and create jobs.

## Running it

```
./bmu test                      # starts the test stack afresh, runs every test (headless)
./bmu test -k sign_out --headed # one test, with the browser showing
./bmu test-down                 # stops the test stack
```

Needs Docker, Python 3.11 (or `BMUT_PYTHON` naming one) and Chrome. The first run makes `bmut/.venv`; Selenium Manager (part of Selenium) finds
the matching chromedriver. A run takes the stack's start-up (a few minutes the first time, while the images build)
plus the tests.

- **Its own stack.** `./bmu test` runs the Docker Compose project `bmu-test` on its own ports (the app 5573, the API
  8500, the simulator 8580, moto 9500, DynamoDB 8501), so it never touches the stack you use by hand
  (`./bmu up sim`). Every store is in memory and each run starts the stack afresh, so every run begins from the same
  data. It makes its own session and job keys each run, so it needs no `.env`.
- **Every moment is a run time** (`BMU_ALWAYS_RUN_TIME=true`), so a submitted job runs at once.
- **It's left running afterwards**, to look at what a failed test saw: http://localhost:5573 (`admin` / `admin`).
- **When a test fails,** its screenshot and the page's HTML are saved in `bmut/.run/failures/`, and the test's report
  says so.
- The suite refuses to run unless `./bmu test` started it (`BMUT_STACK=test`) on a localhost address.
- **CI runs it too**: the `bmut` job in `.github/workflows/ci.yml`, on every pull request and push to `main` that
  changes more than documentation, on GitHub's Linux runners (Docker and Chrome come with them; `BMUT_PYTHON` points
  `./bmu test` at setup-python's Python). When it fails, the run's artifacts hold `bmut-failures` (the screenshots
  and page HTML), and the log ends with each service's last 200 lines. It isn't a required check yet (testing
  checklist section 17). Still run `./bmu test` yourself before pushing a UI change: it's quicker than waiting for CI.

## How the tests are ordered

- **Each test has its own browser**, so a sign-in or a dark-mode choice ends with the test. A file that works
  through drafts as people would keeps one browser per user for all its tests instead (`admin`, `intern`, `limited`;
  `conftest.signed_in_browser`): a second sign-in as the same user is a session of its own, and finds a draft the
  first has open held by it. A failed test saves a screenshot of each browser it used.
- **The files run in `conftest.py`'s `FILE_ORDER`**: what only looks first (sign-in, then the tabs), then what changes
  the stack's data (the job flow, then roles, three kinds of result, Submit for review, and Drafts and Job queue). Each file's tests run in file order, never in parallel or shuffled. A new file goes
  where its changes belong.
- **A test that builds on an earlier one** says so with `@pytest.mark.after("test_name")`: if that test didn't pass,
  it's skipped rather than failing for the same reason.

## Where the tests come from

`docs/testing-checklist.md` says what to check by hand; each test's docstring names the section and step it automates.

| Tests | What |
| --- | --- |
| `tests/test_sign_in.py` | Sign-in and sign-out (section 2): returning to the page asked for, a wrong password, empty fields (no request sent), the environment label, accounts refused at sign-in (`newstaff`, `reader`; section 2i), signing out, a session that ended |
| `tests/test_tabs.py` | Tabs as pages (section 2): a reload keeps the tab, Back goes through the tabs, the browser tab's title, Page not found, dark mode |
| `tests/test_job_flow.py` | One job from start to finish (sections 2, 2a, 2b): naming a job gives the address its id, two files upload and are found in CollectionSpace, a reload keeps the draft, Drafts and back, Submit lands on Job queue, and the run ends Completed in Finished jobs |
| `tests/test_roles.py` | Roles (sections 2i, 2j, 2k), as `admin` and `intern`: the Intern chip and the Job queue's controls, "Staff only" and "Open to interns" drafts, what an intern can't edit and why, Open to interns from Drafts and from the editor, Submit… from Drafts (and off when a document needs fixing), an intern's checks through the read-only account (a missing Object, a protected file and an access note, without the reasons staff see) |
| `tests/test_three_kinds_of_result.py` | Three kinds of result (section 2l), as `limited`, `admin` and `intern`: "Needs an Object creator" in the document, the job's purple line and the bar, Submit job off until the document is deleted, the Drafts chip for each user, `admin` submitting it to Completed, the group problem that stops only Submit |
| `tests/test_submit_for_review.py` | Submit for review (section 2m), as `intern` and `admin`: off while a document needs fixing, then sent from the editor and from Drafts; the "Needs review" mark, first in Drafts and staff only; the mark kept through a staff edit, cleared by Open to interns, and gone after Submit… and Move to Drafts |
| `tests/test_drafts_and_queue.py` | Drafts and Job queue (sections 2c, 2i, 2j): a draft's line, details and full preview, Expand and Collapse all, sorting, Take over… from a second session, deleting a draft; with the queue paused, two queued jobs, Run now, Hold, Set run time, the arrows, what an intern sees, Move to Drafts…, and Edit on a queued job |

The files are named for the simulator's sample Objects (`backend/fakecspace/app.py`, `SAMPLE_OBJECTS` and
`SENSITIVE_OBJECTS`), or for object numbers it doesn't have (20-0777, 20-0990 and up) where a test needs a missing
Object, and the image is a 20-pixel JPEG from the frontend's fixtures (`files.py`). Every moment is a run time on the
test stack, so a test that needs jobs to wait in the Job queue pauses the queue first and resumes it afterwards
(`QueuePage.pause`).

Chrome's password manager is off in the tests' browsers: after signing in as `intern` / `intern`, a password on
Chrome's list of leaked ones, its "Change your password" bubble took every key and click the test sent.

## Packages

Pinned with hashes in `requirements.txt`; change `requirements.in` and run, with Python 3.11 and the pip-tools in
`backend/requirements-tools.txt`:
`pip-compile --generate-hashes --allow-unsafe --strip-extras -o requirements.txt requirements.in`. Dependabot
(`.github/dependabot.yml`) proposes updates every Monday. The suite needs nothing beyond pytest and Selenium.
