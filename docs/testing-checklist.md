# BMU testing to do (checks by hand)

These are things Claude couldn't test, to be checked by hand. The list was started on October 3, 2026, after parts 1 and 2 of the Vuetify conversion were merged (PRs #36 and #37), and a section was added for each later piece of work. Tick an item when it's done, and note anything odd under it.

This list moved into the repository on October 5, 2026, from "BMU Testing To Do" in Richard's personal Claude account. That copy is no longer kept up to date. Change this file through pull requests, like `docs/design.md`. When a pull request needs checks by hand, add a section here in the same pull request.

Each section was written for its own branch. Later work has changed some screens, so where a step no longer matches `main`, the step says what replaced it. The automated test counts quoted in sections 1 and 2a are the counts at that time. Today, expect every test to pass.

Already done on October 3: a quick look at `./bmu up sim`, and browser uploads continuing while on other tabs.

## 1. Backend suite (5 minutes)

Not run for parts 1 or 2. The only backend change was the license line in `backend/pyproject.toml`.

- [ ] On `main`, run the full backend suite: `cd backend && pytest -q`. Expect every test to pass (328 on October 3).

## 2. The new frame, in `./bmu up sim` (15 minutes)

Start with `./bmu up sim`, open http://localhost:5173.

**Sign-in**

- [ ] Signed out, open http://localhost:5173/queue directly. Expect the sign-in page; after signing in, expect the Job queue tab, not Create / edit job.
- [ ] Sign in with a wrong password. Expect the reason in red under the fields, the password field emptied, and the username kept.
- [ ] Click Sign in with both fields empty. Expect "Enter your CollectionSpace username and password." and no request to the server.
- [ ] The environment label ("Local · simulated CollectionSpace") shows above the sign-in card and in the app bar.

**Tabs as pages**

- [ ] On each of the four tabs, reload the browser. Expect to stay on the same tab.
- [ ] Click through several tabs, then use the browser's Back button. Expect to go back through the tabs.
- [ ] The browser tab's title names the page, for example "Drafts | BMU · Local · simulated CollectionSpace".
- [ ] Open http://localhost:5173/nonsense. Expect "Page not found" with a button back to Create / edit job.

**The job being worked on, across tabs**

- [ ] Start a job and add a few files. Go to Drafts and back. Expect the editor exactly as you left it (same rows, same expanded row, same selection).
- [ ] With a large file uploading (Demo tools: slow the browser upload), go to Job queue, wait, come back. Expect the upload to have continued or finished.
- [ ] From Drafts, click Edit (or Continue editing) on a draft. Expect Create / edit job to open with that draft.
- [ ] From Drafts, open the preview of a different draft while one is open in the editor: expand that draft and click "Open full preview". (Rows had a Preview button until October 5, 2026; see 2n.) Expect the preview inside the Drafts tab; go to Create / edit job and expect your open draft untouched.
- [ ] Submit a job. Expect to land on Job queue with the blue message saying when it runs. Close the message with its ×.
- [ ] Click New job while a draft is open. Expect an empty editor; in Drafts, the earlier draft is no longer shown as being edited by you.

**Sign out and session end**

- [ ] Open a draft, then use the menu under your username to Sign out. Sign in as a different user: expect to be able to edit that draft without "Take over".
- [ ] Let a session time out (or delete the `bmu_session` cookie in the browser's developer tools), then click something. Expect the sign-in page with the reason shown in a yellow box; after signing in, expect to return to the tab you were on.

**Dark mode**

- [ ] In the menu under your username, choose Dark mode. Expect the whole page to go dark, the menu item to read "Light mode", and the choice to survive a reload and a sign-out.
- [ ] Look at each tab in dark mode for anything unreadable. The old tab contents are greyer than the frame until they are converted; that is expected. Unreadable text or white boxes are not.
- [ ] Clear the choice (developer tools: remove `prefersDarkMode` from Local Storage) and reload. Expect the page to follow the Mac's light or dark setting.

**View-only account (replaced by the roles work)**

- Since roles part 1 (2i), a user without create and update on Media records is refused at sign-in: there is no "View only" mode. Test it with the `newstaff` user in 2i.

**Demo tools**

- [ ] The Demo tools pane opens, collapses and remembers its state; one control works (for example, slow the browser upload). It moved inside the new frame unchanged, but was never run against the real simulator.

**Keyboard and screen reader (optional, 5 minutes)**

- [ ] From a fresh page load, press Tab once. Expect a "Skip to main content" link to appear at the top left.
- [ ] Open the user menu with the keyboard (Tab to it, Enter), move with the arrow keys, close with Escape.

## 2a. Create / edit job after part 3 (20 minutes)

Once `feature/vuetify-editor` is merged (or on that branch), in `./bmu up sim`. This screen was rebuilt; Claude saw it only in screenshots against a stand-in API.

- [ ] Backend suite still 328 passed (no backend file changed).
- [ ] Drop files on the drop area, and pick files with "browse". Rows appear, thumbnails load, uploads show progress and finish.
- [ ] Expand a row, edit each kind of field: file name, object number (and "Use parsed value"), date, media type (and "Add an additional type"), creator (type three letters, pick from the list with mouse and with arrow keys), description, language. Reload the page: the edits are kept.
- [ ] Change a row's handling, Restricted and Exclude. The status chip and the Public portal column follow.
- [ ] Delete one document with its trash can: the confirmation appears under the row; Cancel and Delete both work.
- [ ] Select rows, then in "Change selected documents": Apply to selected, Apply to all (with its confirmation), Exclude, Include and Delete selected.
- [ ] Sort by each column; change page and page size; "Show documents with problems".
- [ ] With 30 or more documents, click the header chevron to expand all, then scroll. Expect each document's fields to be there as it comes into view, with no visible jump or blank gap.
- [ ] Turn on "Create a group", give a title, submit; the group box and a row's Group checkbox behave as before.
- [ ] A failed upload (Demo tools): Replace file and Retry work from the row.
- [ ] Open a draft someone else is editing: the locked banner and "Take over" work.
- [ ] Save draft and Submit job; with a must-fix document, Submit is refused and says why.
- [ ] Dark mode: every part of the screen is readable, including expanded rows and the delete confirmation.
- [ ] If you have a large draft (several hundred documents), page through it at 100 per page. Changing page measured about 0.4 s, twice what it was; say if it feels slow.

## 2b. Reload and deleting (5 minutes)

On branch `fix/editor-reload-and-deleting` (or `main` once it is merged), in `./bmu up sim`. On October 3 Richard ran 21 checks of Create / edit job by hand; 20 passed, and these two changes followed.

- [ ] Open a draft, edit a field, reload the browser. Expect the same draft open, with the edit, and the address ending in `/job/` and the job's id.
- [ ] Start a new job by typing a name. Expect the address to gain the job's id. Reload: the job is still open.
- [ ] With a draft open, go to Drafts and back by the Create / edit job tab. Expect the draft still open.
- [ ] Click New job, then the browser's Back button. Expect the earlier draft to reopen.
- [ ] Delete a draft from Drafts, then paste its old address. Expect a message that the job isn't there, and a new, empty job.
- [ ] Select 3 documents and Delete selected. Expect the three rows to read "Deleting…" and dim, and the button to read "Deleting…", until they disappear. Note roughly how long it takes.

## 2c. Drafts and Job queue after part 4 (20 minutes)

On branch `feature/vuetify-lists` (or `main` once it is merged). Run `./bmu down sim` and `./bmu up sim` first: this part changed the backend, and the web image is only rebuilt on `up`. Claude saw these pages only in screenshots against a stand-in API.

**Drafts**

- [ ] The list shows each draft's checks, last saved, who is editing and expiry. Expand a draft: its facts and its documents appear; "Open full preview" opens the preview.
- [ ] Sort by each column heading. Expand all and Collapse all.
- [ ] Delete a draft: the confirmation opens in a full-width row under the draft, the draft's buttons are off meanwhile, Cancel closes it, Delete draft removes the draft.
- [ ] As a second user, a draft someone else is editing shows Take over…; the warning opens under the draft; Take over and edit opens it.
- [ ] Open a draft's full preview (expand the draft, then "Open full preview"; the row's Preview button was removed on October 5, 2026, see 2n): Back to Drafts, Check again, the Show filter, paging and sorting work; Edit opens Create / edit job.

**Job queue**

- [ ] Submit two or three jobs. The banner shows the schedule and the next run time; each job shows Runs at.
- [ ] As staff (`admin`; this said "a scheduler" before roles part 1 replaced BMU\_Scheduler with BMU\_Staff): Schedule settings (change days and times, Save; try run days more than 3 days apart and expect the server's message in the panel), Pause queue with a reason, Resume queue.
- [ ] Run now and Undo Run now, Hold and Release, Set run time (Save, Clear, Cancel) on a queued job.
- [ ] Reorder with the arrows and by dragging. Sort by a column: the "Sorted view" note appears and moving is off until the sort is cleared.
- [ ] Edit on a queued job: the warning opens under the job; Edit anyway moves it to Drafts and opens it.
- [ ] While a job runs: the spinner, the done / failed / to go line, the bar and "Now: file, step" update; Cancel run asks first, then the job stops after the document in progress.
- [ ] Open a running job's full preview (expand it, then "Open full preview"): each document's run state updates.
- [ ] As `intern` (this said "a user without the scheduler role" before roles part 1): no schedule buttons and no arrows. Since roles part 1, any staff member can cancel any run; an intern can't cancel one (see 2i).

**Deleting many documents (the backend change)**

- [ ] In a draft with 20 or more uploaded documents, select them all and Delete selected. Note the time; before this change 3 documents took about 2 seconds.
- [ ] Afterwards the remaining documents, the count at the bottom and the thumbnails are right. (The "Row deleted" audit entries are covered by the backend tests; the prototype has no audit screen.)

**Dark mode**

- [ ] Both pages, an expanded job, an open confirmation, the schedule panel and a preview are readable.

## 2d. Finished jobs after part 5 (10 minutes)

On branch `feature/vuetify-finished` (or `main` once it is merged), in `./bmu up sim`. Claude saw this page only in screenshots against a stand-in API. Use Demo tools to make a job need attention and one fail.

- [ ] The list shows each job's outcome chip, documents by result, when it finished and who ran it. Sort by each column; Expand all and Collapse all.
- [ ] Expand a job: its run line and its most important documents appear, with what happened; "View all N documents' results" opens the results.
- [ ] View results: run history newest first, each document's steps with CSIDs, failures with "Show technical details"; the Show filter, sorting and paging work; "Back to finished jobs" returns to the list.
- [ ] A job whose failures only need another run reads Reschedule; one that needs a change reads Fix and reschedule. Either opens the job in Create / edit job.
- [ ] Delete a job from the list: the confirmation opens in a row under the job and says what stays in CollectionSpace; Cancel closes it; Delete job removes the job and shows the blue message.
- [ ] Delete from inside a job's results: the confirmation takes the place of the buttons; after deleting you are back at the list.
- [ ] A completed job shows "Removed" and a date, and no Fix or Delete.
- [ ] As `intern` (this said "a view-only user" before roles part 1): Fix and Delete are off, with the reason on hover.
- [ ] Dark mode: the list, an expanded job, the results and an open confirmation are readable.

## 2e. Demo tools after part 6 (10 minutes)

On branch `feature/vuetify-demo-tools` (or `main` once it is merged), in `./bmu up sim`. The pane was rebuilt; Claude saw it only in screenshots against a stand-in API, and never used its controls against the real demo endpoints.

- [ ] The pane opens and collapses with its triangle; collapsed, it shows the one-line summary; the state survives a reload.
- [ ] Slow down file transfers: set Browser uploads to 1 MB/s and add a large file; the upload is visibly slow. Set it back to Full speed.
- [ ] Make CollectionSpace fail: add a failure for the upload step, run a job, and see the document fail; the failure's "left" count goes down; Clear failures removes it.
- [ ] Change terms: delete a person, rename a language; the change is listed in the pane and shows in a draft's checks.
- [ ] Reset: Reset simulated CollectionSpace; Delete all jobs… asks first, Cancel closes it, Delete all jobs empties the lists and the message appears.
- [ ] "Sample objects" and "Check scripts and other commands" open; Copy puts a command on the clipboard.
- [ ] Dark mode: the pane is readable, and native lists and checkboxes across the app (the editor's rows, Show filters, page size) are dark, not white.
- [ ] `./bmu up qa` (Demo off): the pane says demo tools are off and still lists the commands.

## 2f. After the Vuetify review (10 minutes)

On branch `fix/vuetify-leftovers` (or `main` once it is merged), in `./bmu up sim`. Vuetify was upgraded (3.11.7 to 3.13.2), so the first item is a general look.

- [ ] Click through sign-in, the editor (with an expanded row), Drafts, Job queue, Finished jobs and a job's results, in light and dark mode. Nothing should look different from before except the items below.
- [ ] Keyboard: press Tab through a page. Each button, tab and link shows a solid outline when it has the focus; a mouse click doesn't show one. Open the user menu and an expansion panel ("Sensitivity and publishing") with the keyboard: their focus outline is visible too (Claude did not look at these two).
- [ ] Job queue as staff (`admin`): the move arrows are easy to click (28 pixels); Set run time's Save, Clear and Cancel are the same size as other buttons.
- [ ] A failed upload in the editor (Demo tools): Retry and Remove are normal-sized buttons and the row isn't noticeably taller.
- [ ] Loading: in the browser's developer tools set the network to "Slow 4G", then open Drafts, Job queue and Finished jobs. Each says "Loading…" first, never "No drafts" or "No jobs".
- [ ] Stop the web container (`docker compose -p bmu-sim stop web`), reload Drafts: an error shows, with no "No drafts" under it. Start it again.

## 2g. Jobs that collide in the queue (15 minutes)

On branch `feature/demo-reset` (it contains `feature/queue-collisions`), or `main` once both are merged. Run `./bmu down sim` and `./bmu up sim` first: this is a backend change. Claude ran it only in the tests and one screenshot. Use an object number that doesn't exist, such as 11-2345.

**At Submit**

- [ ] Job A: one file, "Create new object + link", object 11-2345; submit. Job B the same: expect "Must fix" naming Job A and offering "Link to object (create if missing)", and Submit refused.
- [ ] Change Job B's document to "Link to object (create if missing)": the Must fix goes, a warning about the same identification number stays, Submit works.
- [ ] Job A "Link to object (create if missing)" queued first, then Job B "Create new object + link": B is refused at Submit.
- [ ] Two jobs that both use "Link to object (create if missing)": both submit.

**Changing the order** (A "Create new object" first, B "create if missing" second, both queued)

- [ ] Move B above A with the arrow. Expect a question under B naming A's document, with "Move anyway" and Cancel; Cancel leaves the order alone.
- [ ] Move again and choose "Move anyway". Expect A's "Checks now" to read "1 needs fixing" at once, and a box above the list naming the document.
- [ ] Same question for Run now on B, and for Hold on A; drag and drop asks too.
- [ ] In a second browser signed in as `limited`, with the Job queue open: after the move it shows the box and the flag within a few seconds, without a reload, and no Reorder button.

**Reorder to avoid failures**

- [ ] Click "Reorder to avoid failures…": it says what it will move; Cancel does nothing; Reorder puts A first, the box and the flag go, and other jobs keep their places.
- [ ] Give B Run now ("Run now anyway"). Expect the box to say a reorder can't fix it and to name the Run now; B's Run now is not undone.
- [ ] Leave the order broken and let both run. Expect B Completed, and A Needs attention with that document Failed ("Object already exists") and nothing created for it.

## 2h. Demo tools: Reset everything (5 minutes)

On branch `feature/demo-reset` (or `main` once it is merged), after `./bmu down sim` and `./bmu up sim`. Claude ran it only in the tests.

- [ ] With a draft, a queued job and a finished job, change the schedule, then Demo tools, Reset everything…, confirm. Expect empty Drafts, Job queue and Finished jobs, the schedule back to every day at 7:00 PM, and to be still signed in.
- [ ] Cancel in the confirmation changes nothing.
- [ ] While a job is running (slow the run down first), Reset everything is refused with a message naming the job.
- [ ] After a reset, make and run a new job: it works as on a fresh start.
- [ ] `./bmu up qa`: the pane has no Reset everything button (Demo tools are off there).

## 2i. Roles, part 1: staff and interns (15 minutes)

Branch `feature/roles-and-sign-in`. The backend changed, so restart first: `./bmu down sim`, then `./bmu up sim`. The simulator's users are listed in the README (Running it locally); each one's password is `<simulator-password>` (see the README).

- [ ] Demo tools has a "Sign in as" box. It says who you are and your role, and has one button for each simulator user. Use it for the switches below instead of signing out and in. Its buttons for `reader` and `newstaff` show the refusal message and leave you signed in as you were.
- [ ] Clicking a "Sign in as" button for a user who is let in reloads the app as that user, on Create / edit job.
- [ ] Sign in as `reader`: refused, with a message that the account has neither BMU role and to contact the CollectionSpace administrator.
- [ ] Sign in as `newstaff`: refused, with a message naming what the account can't do (create and update Media records, create relations).
- [ ] Sign in as `admin`: works as before. No "Intern" chip in the header. The Job queue has every control (reorder, Run now, Set run time, Hold, Schedule settings, Pause queue).
- [ ] As `admin`, create a draft, add a file and close it (New job). In Drafts it reads "Staff only" under its name.
- [ ] Sign in as `intern` (a private window keeps `admin` signed in): the header shows "Intern". New job works; add a file. In Drafts the intern's draft reads "Open to interns", and its Edit and Delete work.
- [ ] As `intern`, in Drafts: Edit and Delete on `admin`'s draft are off, and the tooltip says "This draft is for staff only."
- [ ] As `intern`, in the editor: Submit job is off, and its tooltip says only staff can submit. Expected for now: the documents show "needs fixing" because the intern's account can read nothing (the service account comes in part 3).
- [ ] As `intern`, in the Job queue (submit a job as `admin` first): no reorder arrows or run controls, the line "Only staff can change the schedule or the order of the queue", and Edit and Delete off with "Only staff can do this."
- [ ] As `intern`, in Finished jobs: Fix and reschedule and Delete are off.
- [ ] As `admin`, open the intern's draft and submit it: it runs under `admin`.
- [ ] As `limited` (staff who can't create Objects): signs in; behaves as before.

## 2j. Roles, part 2: intern access, Submit from Drafts, Move to Drafts (15 minutes)

Branch `feature/intern-access`. Restart first: `./bmu down sim`, then `./bmu up sim`. Use the Demo tools "Sign in as" box to switch users.

- [ ] As `admin`, in Drafts: a draft with nothing to fix has Submit… on. Click it: the confirmation names the document count, who created and last saved the draft, and says it runs with your sign-in. Cancel changes nothing.
- [ ] Confirm the submit: you land in the Job queue with the usual "was submitted" message, and the job runs as `admin`.
- [ ] A draft with a document that needs fixing has Submit… off, and the tooltip says to open the draft with Edit.
- [ ] As `admin`, "Open to interns" on a draft's row: the line under its name changes, and a message says so. "Make staff only" changes it back.
- [ ] As `admin`, open a draft: the "Open to interns" checkbox under the job name does the same.
- [ ] As `intern`, open a draft that is open to interns. In a private window as `admin`, make it staff only. Back as the intern, the next change is refused and the page says the draft is no longer theirs to edit.
- "Hand over to staff…" is gone: Submit for review replaced it on October 5, 2026. Test that in 2m instead. The two steps that were here no longer apply.
- [ ] As `admin`, in the Job queue: "Move to Drafts…" on a queued job asks first, then the job is in Drafts with nobody editing it.
- [ ] As `intern`, in the Job queue: "Move to Drafts…" is off, with "Only staff can do this."
- [ ] Still expected: an intern's documents show "needs fixing" (part 3).

## 2k. Roles, part 3: the read-only account for interns' checks (15 minutes)

Branch `feature/reader-account`. Restart first: `./bmu down sim`, then `./bmu up sim`. Use the Demo tools "Sign in as" box to switch users.

- [ ] As `intern`, create a job and add a file named `15-1234_1.jpg`. Expect no "can't read Object records" or "can't read Media records" message. Still expected until part 4: "can't update Media" or "can't create relations".
- [ ] As `intern`, add `20-0777_1.jpg`. Expect "No object 20-0777 in CollectionSpace": a real finding, made for the intern.
- [ ] As `intern`, add `12-2001_1.jpg`. Expect a protected file whose reason reads "marked sensitive in CollectionSpace", with no mention of Human Remains or "culturally", and no thumbnail.
- [ ] As `intern`, add `12-2003_1.jpg`. Expect the warning "Object 12-2003 has a note about access in CollectionSpace", without the kind of restriction.
- [ ] Sign in as `admin` and preview the same draft: the full reasons are there.
- [ ] As `intern`: the Creator field's search finds terms, the Language list fills, and a date such as `1920s` gets its preview.
- [ ] `./bmu logs sim web` shows lines like "reader: intern made 3 lookups (checking job …)".
- [ ] The sign-in page refuses `bmureader` / `<simulator-password>`, and "Sign in as" doesn't list it.

## 2l. Roles, part 4: three kinds of result (20 minutes)

Branch `feature/three-kinds-of-result`. Restart first: `./bmu down sim`, then `./bmu up sim`. Use the Demo tools "Sign in as" box to switch users. `limited` is staff who can't create objects or groups.

- [ ] As `limited`, create a job with `20-0990_1.jpg` and `15-1234_1.jpg`. Set the first to "Link to object (create if missing)". Expect its Status to read "Needs an Object creator" in purple, not "Needs fixing", and one purple line at the top of the job.
- [ ] The bar under the table reads "nothing to fix · 1 needs an Object creator". Submit job is off, and its tooltip says why.
- [ ] The handling list offers "Create new object + link (needs an Object creator)", and it can be chosen.
- [ ] There is no "Submit without…" button: a job is submitted whole. The purple line says to leave the draft for a colleague, change the handling, or delete the document from this job.
- [ ] Delete that document from the job: Submit job comes on.
- [ ] Make such a draft again, save it and sign in as `admin`: Submit… from the Drafts list works, the job runs and is Completed, and object 20-0990 exists in the simulator.
- [ ] In the Show list, "With problems" does not count the document; "Need an Object creator" does.
- [ ] As `limited`, save such a draft. In Drafts its checks chip is purple: "nothing to fix · 1 needs an Object creator", and Submit… is off with the reason. As `admin` the same chip reads "nothing to fix · 1 new Object", and Submit… is on.
- [ ] As `limited`, a job with `15-1234_1.jpg` and "Create a group" ticked with a title: one orange message beside the group says to contact the CollectionSpace administrator. The document does not read "Needs fixing". Submit job is off.
- [ ] Untick Group on the document: the message goes and Submit job is on.
- [ ] As `intern`, add `15-1234_1.jpg`: no "Must fix" about Media or relations. Add `20-0991_1.jpg` set to "Link to object (create if missing)": "Needs an Object creator", with "The staff member who submits the job must be able to create Objects."
- [ ] As `intern`, add `20-0777_1.jpg` left on "Link to existing object": "Needs fixing" with "No object 20-0777", a real problem.
- [ ] Check the purple in dark mode too, if you use it: say if it is hard to read.

## 2m. Submit for review (10 minutes)

Branch `feature/submit-for-review`, built on part 4. Restart first: `./bmu down sim`, then `./bmu up sim`. Use the Demo tools "Sign in as" box to switch users.

- [ ] As `intern`, create a job with `15-1234_1.jpg` and `20-0777_1.jpg`. At the bottom of the job, where staff have Submit job, the button reads "Submit for review…". It is off, and its tooltip says to fix or exclude the documents that need fixing. There is no Submit job button, and nothing under the job name.
- [ ] Tick Exclude on `20-0777_1.jpg`: "Submit for review…" comes on. Click it: it asks first, in the same bar. Confirm.
- [ ] The editor starts a new job, with a message that the draft was sent for review. In Drafts the job is first in the list, with a blue "Needs review · sent by intern, <time>" mark, and reads "Staff only". Its Edit and Delete are off for the intern.
- [ ] As `intern`, a second job with `20-0993_1.jpg` set to "Link to object (create if missing)" (purple, needs an Object creator): "Submit for review…" is on.
- [ ] As `intern`, in Drafts: "Submit for review…" on a draft's row does the same, and is off with the reason when a document needs fixing.
- [ ] As `admin`, the bottom button still reads Submit job.
- [ ] As `admin`, open the first job with Edit: a blue line says who sent it and when. Change something and close it: the mark is still there.
- [ ] As `admin`, "Open to interns" on that row: the mark goes, and the intern can edit it again.
- [ ] Send it for review again as `intern`, then as `admin` use "Submit…" on its row. It goes to the Job queue. Move it back to Drafts: no "Needs review" mark.
- [ ] The audit log has "Sent for review" entries.

## 2n. No Preview button on the rows (5 minutes)

Branch `feature/no-preview-button`, built on Submit for review. Frontend only: reload the page.

- [ ] Drafts and the Job queue: no Preview button on any row.
- [ ] Expand a job: "Open full preview" is the first line, above the job's facts. It opens the full preview; "Back to Drafts" (or "Back to the job queue") returns.
- [ ] In the full preview, the job's buttons are as before (Edit, Submit…, and so on).
- [ ] Finished jobs still has "View results".

## 3. The same, against PAHMA QA (10 minutes)

`./bmu up qa`, http://localhost:5273, with your own QA account. Real records are created.
- [ ] New with the roles work: your QA account needs the BMU_Staff role, or the BMU refuses the sign-in. First run `python scripts/check_cspace.py --roles` with that account: it shows the BMU role and, for each resource in the tenant's `staff_permissions`, what the account has. If `vocabularies` or `structureddates` reads "not listed", tell Claude before going further, because staff could not sign in.

- [ ] The environment label is the warning colour (orange) on the sign-in page and in the app bar.
- [ ] Sign in, add one small file linked to an existing object, submit, let it run. Expect the same results as before the conversion.

## 4. AWS (after the next `./bmu aws deploy`)

Carried over from before the Vuetify conversion. The separate web and worker role policies and two new S3 permissions have never run in AWS. Watch `./bmu aws logs web` and `./bmu aws logs worker` for `AccessDenied` throughout.

The ticks below were made on October 5, 2026, from the record of the October 4 to 5 deploy to the personal-dev environment. That deploy covered sign-in, an intern's upload and a thumbnail. It also found that the web app's own S3 writes were refused, and those were fixed (see `docs/design.md`, roles part 3). Every step left unticked hasn't been run yet.

- [x] Sign in.
- [ ] Upload files, including a TIFF (the web app makes its thumbnail, so its role reads the staged file).
- [ ] Submit a job and let it run to the end.
- [ ] Edit a queued job (it moves back to Drafts).
- [ ] Delete a document from a draft, and delete a job.
- [ ] Cancel a running job.
- [ ] New with part 2: reload the browser on `/queue` and on `/drafts`. Expect the page, not an error: the web app serves the app for those addresses, and this is the first time CloudFront and the load balancer are asked for them.
- [ ] `./bmu aws destroy` when finished, if you don't want it left running.
- [ ] Before deploying the roles work: on PAHMA QA, run `python scripts/check_cspace.py --roles` as a staff account. It lists each resource the tenant's `staff_permissions` names, with what the account has. Confirm `vocabularies` and `structureddates` are not shown as "not listed"; if either is, tell Claude, because staff could not sign in.
- [ ] Before deploying: the BMU_Staff and BMU_Intern roles exist in each CollectionSpace and every BMU user has one.

- [x] New with roles part 3 (67 resources on a first deploy; one new secret and one policy change on a later one). Before deploying, in `deploy/terraform/app`: `terraform init -backend=false && terraform validate`, then `terraform test`. Claude could not run either. (Both passed, 9 tests, and a fresh deploy created 67 resources.)
- [ ] `./bmu aws plan` shows the new secret `bmu-dev/cspace-reader`, the `ReaderSecret` statement in the web role's policy and `BMU_READER_SECRET_ID` in both task definitions, and nothing unexpected.
- [ ] After the deploy: `./bmu aws status` reads "Read-only account for interns' checks: NOT SET".
- [x] `./bmu aws reader-secret`: enter the QA reader account's user name and password. Expect "Saved." Then `./bmu aws status` reads "set, last changed <today>". This command has never run against real AWS; if `put-secret-value` complains about `file:///dev/stdin`, tell Claude.
- [ ] Sign in as an intern account and add a file: its object is looked up. `./bmu aws logs web` shows "reader: <user> made N lookups" and no `AccessDenied`.

## Not tests, but still open

- The design doc's "For Richard to address" list (from the October 3 comparison of the doc with the prototype).
