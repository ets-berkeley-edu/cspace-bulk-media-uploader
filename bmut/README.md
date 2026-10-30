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

- **Each test has its own browser**, so a sign-in or a dark-mode choice ends with the test.
- **The files run in `conftest.py`'s `FILE_ORDER`**: what only looks first (sign-in, then the tabs), then what changes
  the stack's data (the job flow). Each file's tests run in file order, never in parallel or shuffled. A new file goes
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

The files are named for the simulator's sample Objects (`backend/fakecspace/app.py`, `SAMPLE_OBJECTS`), and the
image is a 20-pixel JPEG from the frontend's fixtures (`files.py`).

## Packages

Pinned with hashes in `requirements.txt`; change `requirements.in` and run, with Python 3.11 and the pip-tools in
`backend/requirements-tools.txt`:
`pip-compile --generate-hashes --allow-unsafe --strip-extras -o requirements.txt requirements.in`. Dependabot
(`.github/dependabot.yml`) proposes updates every Monday. The suite needs nothing beyond pytest and Selenium.
