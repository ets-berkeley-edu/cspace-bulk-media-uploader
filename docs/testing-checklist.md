# BMU testing to do (checks by hand)

These are things Claude couldn't test, to be checked by hand. The list was started on October 3, 2026, after parts 1 and 2 of the Vuetify conversion were merged (PRs #36 and #37), and a section was added for each later piece of work. Tick an item when it's done, and note anything odd under it.

This list moved into the repository on October 5, 2026, from "BMU Testing To Do" in Richard's personal Claude account. That copy is no longer kept up to date. Change this file through pull requests, like `docs/design.md`. When a pull request needs checks by hand, add a section here in the same pull request.

Each section was written for its own branch. Later work has changed some screens, so where a step no longer matches `main`, the step says what replaced it. The automated test counts quoted in sections 1 and 2a are the counts at that time. Today, expect every test to pass.

Steps marked *Automated* are checked by the Selenium tests in `bmut/` (named after the mark), which CI runs on every pull request that changes code (`bmut/README.md`): they needn't be done by hand while those tests pass. *Partly automated* says what the tests don't check, and only that part is left to do by hand. A pull request that adds a bmut test marks the steps it covers, as its docstring names them. Marked on October 30, 2026, for the 46 tests then in `bmut/`. Section 19's 22 tests marked theirs on October 29.

Already done on October 3: a quick look at `./bmu up sim`, and browser uploads continuing while on other tabs.

## 1. Backend suite (5 minutes)

Not run for parts 1 or 2. The only backend change was the license line in `backend/pyproject.toml`.

- [ ] On `main`, run the full backend suite: `cd backend && pytest -q`. Expect every test to pass (328 on October 3).

## 2. The new frame, in `./bmu up sim` (15 minutes)

Start with `./bmu up sim`, open http://localhost:5173.

**Sign-in**

- [ ] *Automated:* `test_sign_in_returns_to_the_page_asked_for`. Signed out, open http://localhost:5173/queue directly. Expect the sign-in page; after signing in, expect the Job queue tab, not Create / edit job.
- [ ] *Automated:* `test_a_wrong_password`. Sign in with a wrong password. Expect the reason in red under the fields, the password field emptied, and the username kept.
- [ ] *Automated:* `test_empty_fields_ask_without_a_request`. Click Sign in with both fields empty. Expect "Enter your CollectionSpace username and password." and no request to the server.
- [ ] *Automated:* `test_the_environment_label`. The environment label ("Local · simulated CollectionSpace") shows above the sign-in card and in the app bar.

**Tabs as pages**

- [ ] *Automated:* `test_a_reload_keeps_the_tab`. On each of the four tabs, reload the browser. Expect to stay on the same tab.
- [ ] *Automated:* `test_back_goes_back_through_the_tabs`. Click through several tabs, then use the browser's Back button. Expect to go back through the tabs.
- [ ] *Automated:* `test_the_browser_tabs_title_names_the_page`. The browser tab's title names the page, for example "Drafts | BMU · Local · simulated CollectionSpace".
- [ ] *Automated:* `test_page_not_found`. Open http://localhost:5173/nonsense. Expect "Page not found" with a button back to Create / edit job.

**The job being worked on, across tabs**

- [ ] *Partly automated:* `test_the_draft_in_drafts_and_back`; the same expanded row and selection by hand. Start a job and add a few files. Go to Drafts and back. Expect the editor exactly as you left it (same rows, same expanded row, same selection).
- [ ] With a large file uploading (Demo tools: slow the browser upload), go to Job queue, wait, come back. Expect the upload to have continued or finished.
- [ ] *Automated:* `test_a_drafts_line_details_and_preview`. From Drafts, click Edit (or Continue editing) on a draft. Expect Create / edit job to open with that draft.
- [ ] From Drafts, open the preview of a different draft while one is open in the editor: expand that draft and click "Open full preview". (Rows had a Preview button until October 5, 2026; see 2n.) Expect the preview inside the Drafts tab; go to Create / edit job and expect your open draft untouched.
- [ ] *Partly automated:* `test_submit_and_the_run`; closing the message with its × by hand. Submit a job. Expect to land on Job queue with the blue message saying when it runs. Close the message with its ×.
- [ ] Click New job while a draft is open. Expect an empty editor; in Drafts, the earlier draft is no longer shown as being edited by you.

**Sign out and session end**

- [ ] Open a draft, then use the menu under your username to Sign out. Sign in as a different user: expect to be able to edit that draft without "Take over".
- [ ] *Automated:* `test_a_session_that_ended_returns_to_the_tab`. Let a session time out (or delete the `bmu_session` cookie in the browser's developer tools), then click something. Expect the sign-in page with the reason shown in a yellow box; after signing in, expect to return to the tab you were on.

**Dark mode**

- [ ] *Partly automated:* `test_dark_mode_and_back`; the whole page going dark, and the choice surviving a sign-out by hand. In the menu under your username, choose Dark mode. Expect the whole page to go dark, the menu item to read "Light mode", and the choice to survive a reload and a sign-out.
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
- [ ] *Partly automated:* `test_name_a_job_and_add_files`; dropping files, and thumbnails and progress by hand. Drop files on the drop area, and pick files with "browse". Rows appear, thumbnails load, uploads show progress and finish.
- [ ] *Automated:* `test_edit_each_kind_of_field_and_reload`. Expand a row, edit each kind of field: file name, object number (and "Use parsed value"), date, media type (and "Add an additional type"), creator (type three letters, pick from the list with mouse and with arrow keys), description, language. Reload the page: the edits are kept.
- [ ] *Automated:* `test_handling_restricted_and_exclude`. Change a row's handling, Restricted and Exclude. The status chip and the Public portal column follow.
- [ ] *Automated:* `test_delete_a_document`, `test_a_document_that_needs_an_object_creator`. Delete one document with its trash can: the confirmation appears under the row; Cancel and Delete both work.
- [ ] *Automated:* `test_change_selected_documents`. Select rows, then in "Change selected documents": Apply to selected, Apply to all (with its confirmation), Exclude, Include and Delete selected. (Apply to all has no confirmation now: it applies at once. Delete selected asks first.)
- [ ] *Automated:* `test_sort_page_and_show_problems`. Sort by each column; change page and page size; "Show documents with problems".
- [ ] With 30 or more documents, click the header chevron to expand all, then scroll. Expect each document's fields to be there as it comes into view, with no visible jump or blank gap.
- [ ] *Automated:* `test_a_group`. Turn on "Create a group", give a title, submit; the group box and a row's Group checkbox behave as before.
- [ ] *Automated:* `test_a_failed_upload_and_retry`, `test_fix_and_reschedule_with_a_replacement_file`. A failed upload (Demo tools): Replace file and Retry work from the row. (Replace file follows a run whose upload Demo tools failed; for Retry the test stops the browser reaching S3, since Demo tools only slow browser uploads.)
- [ ] *Automated:* `test_locked_banner_and_take_over`, `test_take_over_a_draft`. Open a draft someone else is editing: the locked banner and "Take over" work.
- [ ] Save draft and Submit job; with a must-fix document, Submit is refused and says why.
- [ ] Dark mode: every part of the screen is readable, including expanded rows and the delete confirmation.
- [ ] If you have a large draft (several hundred documents), page through it at 100 per page. Changing page measured about 0.4 s, twice what it was; say if it feels slow.

## 2b. Reload and deleting (5 minutes)

On branch `fix/editor-reload-and-deleting` (or `main` once it is merged), in `./bmu up sim`. On October 3 Richard ran 21 checks of Create / edit job by hand; 20 passed, and these two changes followed.

- [ ] *Automated:* `test_edit_each_kind_of_field_and_reload`, `test_name_a_job_and_add_files`. Open a draft, edit a field, reload the browser. Expect the same draft open, with the edit, and the address ending in `/job/` and the job's id.
- [ ] *Automated:* `test_name_a_job_and_add_files`. Start a new job by typing a name. Expect the address to gain the job's id. Reload: the job is still open.
- [ ] *Automated:* `test_the_draft_in_drafts_and_back`. With a draft open, go to Drafts and back by the Create / edit job tab. Expect the draft still open.
- [ ] Click New job, then the browser's Back button. Expect the earlier draft to reopen.
- [ ] Delete a draft from Drafts, then paste its old address. Expect a message that the job isn't there, and a new, empty job.
- [ ] Select 3 documents and Delete selected. Expect the three rows to read "Deleting…" and dim, and the button to read "Deleting…", until they disappear. Note roughly how long it takes.

## 2c. Drafts and Job queue after part 4 (20 minutes)

On branch `feature/vuetify-lists` (or `main` once it is merged). Run `./bmu down sim` and `./bmu up sim` first: this part changed the backend, and the web image is only rebuilt on `up`. Claude saw these pages only in screenshots against a stand-in API.

**Drafts**

- [ ] *Partly automated:* `test_a_drafts_line_details_and_preview`; last saved, and the documents under an expanded draft by hand. The list shows each draft's checks, last saved, who is editing and expiry. Expand a draft: its facts and its documents appear; "Open full preview" opens the preview.
- [ ] *Partly automated:* `test_expand_all_collapse_all_and_sort`; sorting by the other columns (the test sorts by one) by hand. Sort by each column heading. Expand all and Collapse all.
- [ ] *Automated:* `test_delete_a_draft`. Delete a draft: the confirmation opens in a full-width row under the draft, the draft's buttons are off meanwhile, Cancel closes it, Delete draft removes the draft.
- [ ] *Automated:* `test_take_over_a_draft`. As a second user, a draft someone else is editing shows Take over…; the warning opens under the draft; Take over and edit opens it.
- [ ] *Partly automated:* `test_a_drafts_line_details_and_preview`; the Show filter, paging and sorting by hand. Open a draft's full preview (expand the draft, then "Open full preview"; the row's Preview button was removed on October 5, 2026, see 2n): Back to Drafts, Check again, the Show filter, paging and sorting work; Edit opens Create / edit job.

**Job queue**

- [ ] *Partly automated:* `test_submitted_jobs_wait_in_a_paused_queue`; the banner's schedule and next run time (the test's queue is paused) by hand. Submit two or three jobs. The banner shows the schedule and the next run time; each job shows Runs at.
- [ ] *Partly automated:* `test_submitted_jobs_wait_in_a_paused_queue`; Schedule settings, and Resume queue by hand. As staff (`admin`; this said "a scheduler" before roles part 1 replaced BMU\_Scheduler with BMU\_Staff): Schedule settings (change days and times, Save; try run days more than 3 days apart and expect the server's message in the panel), Pause queue with a reason, Resume queue.
- [ ] *Partly automated:* `test_run_now_hold_and_set_run_time`; Set run time's Save and Clear by hand. Run now and Undo Run now, Hold and Release, Set run time (Save, Clear, Cancel) on a queued job.
- [ ] *Partly automated:* `test_reorder_with_the_arrows`; dragging, and the sorted view by hand. Reorder with the arrows and by dragging. Sort by a column: the "Sorted view" note appears and moving is off until the sort is cleared.
- [ ] *Automated:* `test_edit_a_queued_job`. Edit on a queued job: the warning opens under the job; Edit anyway moves it to Drafts and opens it.
- [ ] While a job runs: the spinner, the done / failed / to go line, the bar and "Now: file, step" update; Cancel run asks first, then the job stops after the document in progress.
- [ ] Open a running job's full preview (expand it, then "Open full preview"): each document's run state updates.
- [ ] *Partly automated:* `test_an_intern_in_the_job_queue`, `test_staff_and_interns_in_the_header_and_the_job_queue`; that an intern can't cancel a run by hand. As `intern` (this said "a user without the scheduler role" before roles part 1): no schedule buttons and no arrows. Since roles part 1, any staff member can cancel any run; an intern can't cancel one (see 2i).

**Deleting many documents (the backend change)**

- [ ] In a draft with 20 or more uploaded documents, select them all and Delete selected. Note the time; before this change 3 documents took about 2 seconds.
- [ ] Afterwards the remaining documents, the count at the bottom and the thumbnails are right. (The "Row deleted" audit entries are covered by the backend tests; the prototype has no audit screen.)

**Dark mode**

- [ ] Both pages, an expanded job, an open confirmation, the schedule panel and a preview are readable.

## 2d. Finished jobs after part 5 (10 minutes)

On branch `feature/vuetify-finished` (or `main` once it is merged), in `./bmu up sim`. Claude saw this page only in screenshots against a stand-in API. Use Demo tools to make a job need attention and one fail.

- [ ] *Automated:* `test_the_list`. The list shows each job's outcome chip, documents by result, when it finished and who ran it. Sort by each column; Expand all and Collapse all.
- [ ] *Automated:* `test_a_jobs_details_and_results`. Expand a job: its run line and its most important documents appear, with what happened; "View all N documents' results" opens the results.
- [ ] *Partly automated:* `test_a_jobs_details_and_results`; paging (the test's job has two documents) and the run history's order (it has one run) by hand. View results: run history newest first, each document's steps with CSIDs, failures with "Show technical details"; the Show filter, sorting and paging work; "Back to finished jobs" returns to the list.
- [ ] *Partly automated:* `test_fix_labels_and_a_completed_job`, `test_fix_and_reschedule_with_a_replacement_file`; Reschedule opening the job by hand (the test opens Fix and reschedule). A job whose failures only need another run reads Reschedule; one that needs a change reads Fix and reschedule. Either opens the job in Create / edit job.
- [ ] *Automated:* `test_delete_from_the_list`. Delete a job from the list: the confirmation opens in a row under the job and says what stays in CollectionSpace; Cancel closes it; Delete job removes the job and shows the blue message.
- [ ] *Automated:* `test_delete_from_the_results`. Delete from inside a job's results: the confirmation takes the place of the buttons; after deleting you are back at the list.
- [ ] *Automated:* `test_fix_labels_and_a_completed_job`. A completed job shows "Removed" and a date, and no Fix or Delete.
- [ ] *Automated:* `test_an_intern_cant_fix_or_delete`. As `intern` (this said "a view-only user" before roles part 1): Fix and Delete are off, with the reason on hover.
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

- [ ] *Automated:* `test_a_second_create_is_refused_at_submit`. Job A: one file, "Create new object + link", object 11-2345; submit. Job B the same: expect "Must fix" naming Job A and offering "Link to object (create if missing)", and Submit refused.
- [ ] *Automated:* `test_a_second_create_is_refused_at_submit`. Change Job B's document to "Link to object (create if missing)": the Must fix goes, a warning about the same identification number stays, Submit works.
- [ ] *Automated:* `test_create_after_create_if_missing_and_two_create_if_missing`. Job A "Link to object (create if missing)" queued first, then Job B "Create new object + link": B is refused at Submit.
- [ ] *Automated:* `test_create_after_create_if_missing_and_two_create_if_missing`. Two jobs that both use "Link to object (create if missing)": both submit.

**Changing the order** (A "Create new object" first, B "create if missing" second, both queued)

- [ ] *Automated:* `test_a_move_that_would_fail_asks_first`. Move B above A with the arrow. Expect a question under B naming A's document, with "Move anyway" and Cancel; Cancel leaves the order alone.
- [ ] *Automated:* `test_a_move_that_would_fail_asks_first`. Move again and choose "Move anyway". Expect A's "Checks now" to read "1 needs fixing" at once, and a box above the list naming the document.
- [ ] *Partly automated:* `test_a_move_that_would_fail_asks_first`; drag and drop by hand. Same question for Run now on B, and for Hold on A; drag and drop asks too.
- [ ] *Automated, as it is now:* `test_a_move_that_would_fail_asks_first`, with `intern` (roles part 1 made `limited` staff, who have the Reorder button). In a second browser signed in as `limited`, with the Job queue open: after the move it shows the box and the flag within a few seconds, without a reload, and no Reorder button.

**Reorder to avoid failures**

- [ ] *Partly automated:* `test_reorder_to_avoid_failures`; other jobs keeping their places by hand. Click "Reorder to avoid failures…": it says what it will move; Cancel does nothing; Reorder puts A first, the box and the flag go, and other jobs keep their places.
- [ ] *Automated:* `test_run_now_anyway_and_the_run`. Give B Run now ("Run now anyway"). Expect the box to say a reorder can't fix it and to name the Run now; B's Run now is not undone.
- [ ] *Partly automated:* `test_run_now_anyway_and_the_run`; that nothing was created for A's document by hand. Leave the order broken and let both run. Expect B Completed, and A Needs attention with that document Failed ("Object already exists") and nothing created for it.

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
- [ ] *Partly automated:* `test_accounts_without_the_role_or_the_permissions_are_refused`; the message's wording by hand. Sign in as `reader`: refused, with a message that the account has neither BMU role and to contact the CollectionSpace administrator.
- [ ] *Partly automated:* `test_accounts_without_the_role_or_the_permissions_are_refused`; the message's wording by hand. Sign in as `newstaff`: refused, with a message naming what the account can't do (create and update Media records, create relations).
- [ ] *Automated:* `test_staff_and_interns_in_the_header_and_the_job_queue`. Sign in as `admin`: works as before. No "Intern" chip in the header. The Job queue has every control (reorder, Run now, Set run time, Hold, Schedule settings, Pause queue).
- [ ] *Automated:* `test_a_staff_draft_is_staff_only`. As `admin`, create a draft, add a file and close it (New job). In Drafts it reads "Staff only" under its name.
- [ ] *Automated:* `test_an_interns_draft`, `test_staff_and_interns_in_the_header_and_the_job_queue`. Sign in as `intern` (a private window keeps `admin` signed in): the header shows "Intern". New job works; add a file. In Drafts the intern's draft reads "Open to interns", and its Edit and Delete work.
- [ ] *Automated:* `test_a_staff_draft_is_off_for_an_intern`. As `intern`, in Drafts: Edit and Delete on `admin`'s draft are off, and the tooltip says "This draft is for staff only."
- [ ] *Automated, as it is now:* `test_an_interns_draft` (an intern has Submit for review in place of Submit job, 2m; the documents are found, 2k). As `intern`, in the editor: Submit job is off, and its tooltip says only staff can submit. Expected for now: the documents show "needs fixing" because the intern's account can read nothing (the service account comes in part 3).
- [ ] *Automated:* `test_an_intern_in_the_job_queue`. As `intern`, in the Job queue (submit a job as `admin` first): no reorder arrows or run controls, the line "Only staff can change the schedule or the order of the queue", and Edit and Delete off with "Only staff can do this."
- [ ] As `intern`, in Finished jobs: Fix and reschedule and Delete are off.
- [ ] As `admin`, open the intern's draft and submit it: it runs under `admin`.
- [ ] As `limited` (staff who can't create Objects): signs in; behaves as before.

## 2j. Roles, part 2: intern access, Submit from Drafts, Move to Drafts (15 minutes)

Branch `feature/intern-access`. Restart first: `./bmu down sim`, then `./bmu up sim`. Use the Demo tools "Sign in as" box to switch users.

- [ ] *Automated:* `test_submit_from_drafts`. As `admin`, in Drafts: a draft with nothing to fix has Submit… on. Click it: the confirmation names the document count, who created and last saved the draft, and says it runs with your sign-in. Cancel changes nothing.
- [ ] *Automated:* `test_submit_from_drafts`, `test_staff_who_can_create_objects_submit_it`. Confirm the submit: you land in the Job queue with the usual "was submitted" message, and the job runs as `admin`.
- [ ] *Automated:* `test_submit_from_drafts_is_off_when_a_document_needs_fixing`. A draft with a document that needs fixing has Submit… off, and the tooltip says to open the draft with Edit.
- [ ] *Automated:* `test_open_to_interns_from_drafts`. As `admin`, "Open to interns" on a draft's row: the line under its name changes, and a message says so. "Make staff only" changes it back.
- [ ] *Automated:* `test_open_to_interns_in_the_editor`. As `admin`, open a draft: the "Open to interns" checkbox under the job name does the same.
- [ ] As `intern`, open a draft that is open to interns. In a private window as `admin`, make it staff only. Back as the intern, the next change is refused and the page says the draft is no longer theirs to edit.
- "Hand over to staff…" is gone: Submit for review replaced it on October 5, 2026. Test that in 2m instead. The two steps that were here no longer apply.
- [ ] *Automated:* `test_move_to_drafts`. As `admin`, in the Job queue: "Move to Drafts…" on a queued job asks first, then the job is in Drafts with nobody editing it.
- [ ] *Automated:* `test_an_intern_in_the_job_queue`. As `intern`, in the Job queue: "Move to Drafts…" is off, with "Only staff can do this."
- [ ] Still expected: an intern's documents show "needs fixing" (part 3).

## 2k. Roles, part 3: the read-only account for interns' checks (15 minutes)

Branch `feature/reader-account`. Restart first: `./bmu down sim`, then `./bmu up sim`. Use the Demo tools "Sign in as" box to switch users.

- [ ] *Automated:* `test_an_interns_draft`. As `intern`, create a job and add a file named `15-1234_1.jpg`. Expect no "can't read Object records" or "can't read Media records" message. Still expected until part 4: "can't update Media" or "can't create relations".
- [ ] *Automated:* `test_an_interns_checks_use_the_read_only_account`. As `intern`, add `20-0777_1.jpg`. Expect "No object 20-0777 in CollectionSpace": a real finding, made for the intern.
- [ ] *Automated:* `test_an_interns_checks_use_the_read_only_account`. As `intern`, add `12-2001_1.jpg`. Expect a protected file whose reason reads "marked sensitive in CollectionSpace", with no mention of Human Remains or "culturally", and no thumbnail.
- [ ] *Automated:* `test_an_interns_checks_use_the_read_only_account`. As `intern`, add `12-2003_1.jpg`. Expect the warning "Object 12-2003 has a note about access in CollectionSpace", without the kind of restriction.
- [ ] *Automated:* `test_staff_see_the_full_reasons`. Sign in as `admin` and preview the same draft: the full reasons are there.
- [ ] As `intern`: the Creator field's search finds terms, the Language list fills, and a date such as `1920s` gets its preview.
- [ ] `./bmu logs sim web` shows lines like "reader: intern made 3 lookups (checking job …)".
- [ ] The sign-in page refuses `bmureader` / `<simulator-password>`, and "Sign in as" doesn't list it.

## 2l. Roles, part 4: three kinds of result (20 minutes)

Branch `feature/three-kinds-of-result`. Restart first: `./bmu down sim`, then `./bmu up sim`. Use the Demo tools "Sign in as" box to switch users. `limited` is staff who can't create objects or groups.

- [ ] *Automated:* `test_a_document_that_needs_an_object_creator`. As `limited`, create a job with `20-0990_1.jpg` and `15-1234_1.jpg`. Set the first to "Link to object (create if missing)". Expect its Status to read "Needs an Object creator" in purple, not "Needs fixing", and one purple line at the top of the job.
- [ ] *Automated:* `test_a_document_that_needs_an_object_creator`. The bar under the table reads "nothing to fix · 1 needs an Object creator". Submit job is off, and its tooltip says why.
- [ ] *Automated:* `test_a_document_that_needs_an_object_creator`. The handling list offers "Create new object + link (needs an Object creator)", and it can be chosen.
- [ ] *Automated:* `test_a_document_that_needs_an_object_creator`. There is no "Submit without…" button: a job is submitted whole. The purple line says to leave the draft for a colleague, change the handling, or delete the document from this job.
- [ ] *Automated:* `test_a_document_that_needs_an_object_creator`. Delete that document from the job: Submit job comes on.
- [ ] *Automated:* `test_staff_who_can_create_objects_submit_it`. Make such a draft again, save it and sign in as `admin`: Submit… from the Drafts list works, the job runs and is Completed, and object 20-0990 exists in the simulator.
- [ ] In the Show list, "With problems" does not count the document; "Need an Object creator" does.
- [ ] *Automated:* `test_in_drafts_it_waits_for_someone_who_can_create_objects`. As `limited`, save such a draft. In Drafts its checks chip is purple: "nothing to fix · 1 needs an Object creator", and Submit… is off with the reason. As `admin` the same chip reads "nothing to fix · 1 new Object", and Submit… is on.
- [ ] *Automated:* `test_a_group_the_account_cant_create`. As `limited`, a job with `15-1234_1.jpg` and "Create a group" ticked with a title: one orange message beside the group says to contact the CollectionSpace administrator. The document does not read "Needs fixing". Submit job is off.
- [ ] *Automated:* `test_a_group_the_account_cant_create`. Untick Group on the document: the message goes and Submit job is on.
- [ ] *Automated:* `test_an_interns_draft`, `test_an_interns_document_that_needs_an_object_creator`. As `intern`, add `15-1234_1.jpg`: no "Must fix" about Media or relations. Add `20-0991_1.jpg` set to "Link to object (create if missing)": "Needs an Object creator", with "The staff member who submits the job must be able to create Objects."
- [ ] *Automated:* `test_an_interns_checks_use_the_read_only_account`. As `intern`, add `20-0777_1.jpg` left on "Link to existing object": "Needs fixing" with "No object 20-0777", a real problem.
- [ ] Check the purple in dark mode too, if you use it: say if it is hard to read.

## 2m. Submit for review (10 minutes)

Branch `feature/submit-for-review`, built on part 4. Restart first: `./bmu down sim`, then `./bmu up sim`. Use the Demo tools "Sign in as" box to switch users.

- [ ] *Automated:* `test_submit_for_review_waits_for_what_needs_fixing`. As `intern`, create a job with `15-1234_1.jpg` and `20-0777_1.jpg`. At the bottom of the job, where staff have Submit job, the button reads "Submit for review…". It is off, and its tooltip says to fix or exclude the documents that need fixing. There is no Submit job button, and nothing under the job name.
- [ ] *Automated:* `test_exclude_then_submit_for_review`. Tick Exclude on `20-0777_1.jpg`: "Submit for review…" comes on. Click it: it asks first, in the same bar. Confirm.
- [ ] *Automated:* `test_exclude_then_submit_for_review`. The editor starts a new job, with a message that the draft was sent for review. In Drafts the job is first in the list, with a blue "Needs review · sent by intern, <time>" mark, and reads "Staff only". Its Edit and Delete are off for the intern.
- [ ] *Automated:* `test_submit_for_review_from_drafts`. As `intern`, a second job with `20-0993_1.jpg` set to "Link to object (create if missing)" (purple, needs an Object creator): "Submit for review…" is on.
- [ ] *Automated:* `test_submit_for_review_from_drafts`. As `intern`, in Drafts: "Submit for review…" on a draft's row does the same, and is off with the reason when a document needs fixing.
- [ ] *Automated:* `test_staff_review_the_draft`. As `admin`, the bottom button still reads Submit job.
- [ ] *Automated:* `test_staff_review_the_draft`. As `admin`, open the first job with Edit: a blue line says who sent it and when. Change something and close it: the mark is still there.
- [ ] *Automated:* `test_open_to_interns_sends_it_back`. As `admin`, "Open to interns" on that row: the mark goes, and the intern can edit it again.
- [ ] *Automated:* `test_submit_a_reviewed_draft_and_move_it_back`. Send it for review again as `intern`, then as `admin` use "Submit…" on its row. It goes to the Job queue. Move it back to Drafts: no "Needs review" mark.
- [ ] The audit log has "Sent for review" entries.

## 2n. No Preview button on the rows (5 minutes)

Branch `feature/no-preview-button`, built on Submit for review. Frontend only: reload the page.

- [ ] *Automated:* `test_no_preview_button_on_the_rows`. Drafts and the Job queue: no Preview button on any row.
- [ ] *Automated:* `test_no_preview_button_on_the_rows`. Expand a job: "Open full preview" is the first line, above the job's facts. It opens the full preview; "Back to Drafts" (or "Back to the job queue") returns.
- [ ] *Partly automated:* `test_no_preview_button_on_the_rows`; the buttons other than Edit by hand. In the full preview, the job's buttons are as before (Edit, Submit…, and so on).
- [ ] *Automated:* `test_delete_from_the_results`, `test_a_group`. Finished jobs still has "View results".

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

## 5. Pinned backend dependencies (15 minutes, plus the next deploy)

Branch `feature/pin-backend-deps`. The backend now installs exact versions with hashes from `backend/requirements*.txt`. Claude ran the backend suite on Python 3.11 installed only from the pins (395 passed), checked that every pinned package has hashed wheels for Linux ARM64 (the Fargate image) and macOS, and checked that `pin-requirements.sh` reproduces the files exactly. Claude could not build either Docker image: its workspace can't reach Docker Hub or Amazon ECR Public.

- [ ] CI on the pull request: `backend`, `frontend` and the new `dependencies` job pass. Then add `dependencies` to the required checks in the `main` ruleset.
- [ ] `./bmu down all`, then `./bmu up sim`: the images build (watch for "Hashes are required" or "THESE PACKAGES DO NOT MATCH THE HASHES"), sign in, add a file and run a small job.
- [ ] Build a second time after changing only a file in `backend/bmu/`: the `pip install --require-hashes -r requirements.txt` step says CACHED.
- [ ] Next `./bmu aws deploy`: the ARM64 image builds, and the web and worker tasks start (`./bmu aws status`, `./bmu aws logs web`).
- [ ] After merging: run "Dependency audit" once by hand (Actions, Dependency audit, Run workflow). Expect both jobs to pass.
- [ ] The first Dependabot pip PR (a Monday after merging): it should change only `backend/requirements*.txt`, keeping the hashes and the header's options, and not `pyproject.toml`. If it changes `pyproject.toml`, drops hashes or fails to update the files, tell Claude: the fallback is to switch Dependabot off for pip and run `backend/pin-requirements.sh --upgrade` monthly.
- [ ] Dependabot's first Docker PRs offer only patch updates (no Python 3.12+ or Node 24).

## 6. Deploy guards (10 minutes, with the next deploy)

Branch `feature/deploy-guards`. `./bmu aws` now refuses to change a deployed environment's CollectionSpace server or tenant, and the first use of an environment on a computer asks first when the account already holds Terraform state for that name. Claude tested both against stand-ins for `aws` and `terraform` (`backend/tests/test_aws_script.py`), not against AWS, and could not run `terraform test` (2 new runs). CI runs it.

- [x] CI on the pull request: `backend` (the new script tests) and `terraform` (11 runs) pass.
- [x] `./bmu aws plan`: the only changes are the two new outputs, `cspace_url` and `tenant`. Then `./bmu aws deploy` records them.
- [x] In `deploy/environments/personal-dev.local.conf`, add a line `CSPACE_URL=https://example.org` and run `./bmu aws plan`. Expect "'personal-dev' was deployed for https://pahma.qa.collectionspace.org (tenant pahma), but its settings now say https://example.org …" and no plan. Remove the line; `./bmu aws plan` works again.
- [x] The takeover question: copy the `ACCOUNT_ID=` line of `personal-dev.local.conf` somewhere, delete it from the file, and run `./bmu aws status`. Expect the account question, then "This account already has a BMU environment named 'dev' …". Answer `n`: expect "Stopped; nothing was changed." and no `ACCOUNT_ID` line in the file. Run it again and answer `y` twice: the status shows, and the `ACCOUNT_ID` line is back with the same number.

All four done by Richard on October 7, 2026, with the personal-dev environment (PAHMA QA is its recorded server).

## 7. The simulated CollectionSpace in AWS (45 minutes, mostly waiting)

Run this after section 10 (moved there on October 7: the deployment now lists museums). Since PR D, `sim.conf` copied from `personal-dev.conf` has a `CSPACE_TENANTS` line, which the simulator ignores (its museums are PAHMA alone), and `./bmu aws status --env sim` lists "pahma: the simulated CollectionSpace, in the environment" with its read-only account under it. Skip "Before deploying": personal-dev is deployed fresh in section 10.

Branch `feature/simulated-cspace`. Claude ran the backend suite and `deploy/aws.sh` against stand-ins for `aws`, `terraform`, `docker` and `curl` (`backend/tests/test_aws_script.py`). Claude could not run Terraform, build either image or reach AWS. The simulator needs its own environment, because personal-dev's server is PAHMA QA and can't change: these steps use a second environment in the same account, `sim`, and destroy it at the end.

**Before deploying**

- [ ] CI on the pull request: `backend`, `frontend`, `dependencies` and `terraform` (17 runs) pass. Locally, the `TF_DATA_DIR` checks in `deploy/README.md` ("Checking the Terraform code") pass too.
- [ ] personal-dev is unchanged: `./bmu aws plan` shows only `BMU_CSPACE_SIMULATED = "false"` added to both task definitions and the two new outputs (`simulated_cspace`, `fakecspace_image_uri`). Then `./bmu aws deploy`: its production image builds without `backend/fakecspace` and the services start.

**A simulator environment**

- [ ] Create `deploy/environments/sim.conf` by copying `personal-dev.conf` (don't commit it), and `deploy/environments/sim.local.conf` with `BMU_ENV_NAME=sim`, `SIMULATED_CSPACE=true` and `ALWAYS_RUN_TIME=true`.
- [ ] `./bmu aws deploy --env sim`: answer the account question; there's no "is it yours?" question (no `sim` state yet). Two images build (`deploy/Dockerfile`, then `deploy/fakecspace.Dockerfile`), tagged `-dirty` because `sim.conf` isn't committed; the plan creates the `fakecspace` service, the namespace `bmu-sim.internal`, its security group and log group; after the apply, "The read-only account for interns' checks is the simulator's bmureader." and "It uses the simulated CollectionSpace".
- [ ] `./bmu aws status --env sim`: `web`, `worker` and `fakecspace` each "running 1 of 1"; "pahma: the simulated CollectionSpace"; its read-only account "set".
- [ ] Open the address. The label reads "AWS · sim · simulated CollectionSpace", without the warning colour of a real CollectionSpace. Sign in as `admin` / `admin`.
- [ ] Add two files, submit, and let the job run (it starts at once with `ALWAYS_RUN_TIME`). Finished jobs shows it completed, with CSIDs. Watch `./bmu aws logs web --env sim`, `logs worker` and `logs fakecspace` for errors and `AccessDenied`.
- [ ] Sign in as `intern` / `intern` and open a draft: the languages list loads (the reader account works).
- [ ] `./bmu aws reader-secret --env sim` is refused ("uses the simulated CollectionSpace").
- [ ] `./bmu aws pause --env sim`, then `resume --env sim`: all three services stop and start. The finished job's records are gone from the simulator (expected); the job is still listed.
- [ ] `./bmu aws destroy --env sim`: everything goes, including the `bmu-sim-fakecspace` repository and the namespace. If it stops at the VPC or the namespace, run it again a few minutes later. Then delete `sim.conf` and `sim.local.conf`.

## 8. One deployment for several museums: the backend (15 minutes)

Branch `feature/multi-museum-backend` (PR B of the multi-museum work; design: One deployment for several museums). The backend now takes the museum from the session or the job everywhere, keeps a configuration, a CollectionSpace connection and a read-only account per museum, and runs one worker thread per museum. Claude ran the full backend suite on Python 3.11, with new cross-museum tests (`backend/tests/test_museums.py`) that use a second, test-only museum. Only PAHMA has a configuration, so two museums can't be tried by hand yet: the sign-in page's museum list comes with PR C. Here, check that one museum works exactly as before.

- [ ] CI on the pull request: all four jobs pass.
- [ ] `./bmu down all`, then `./bmu up sim` (the images are rebuilt). Sign in as `admin` / `admin`: there's no museum to choose, and the header shows PAHMA.
- [ ] Add two files, check the thumbnails appear, submit, and let the job run. Finished jobs shows it completed.
- [ ] Sign in as `intern` / `intern` and open a draft open to interns: the languages list loads (the read-only account works).
- [ ] `./bmu logs sim worker`: it says "worker … started for tenant pahma", from the thread `worker-pahma`.
- [ ] `./bmu up qa` (optional): sign in with your PAHMA QA account as before.

## 9. One deployment for several museums: the sign-in page (10 minutes)

Branch `feature/museum-sign-in` (PR C of the multi-museum work). The sign-in page lists the museums when the BMU serves more than one, asks for one before anything is sent, signs in there, and remembers the choice in the browser; with one museum nothing changes on the page. The UI mockup's sign-in has the same Museum list. Claude ran the frontend lint, type check, all Vitest tests (three new ones for the museum list) and the production build. Only PAHMA has a configuration, so the list can't appear in `./bmu up sim` yet: the tests cover it with two museums.

- [ ] CI on the pull request passes.
- [ ] `./bmu down all`, then `./bmu up sim`. The sign-in page looks as before (no Museum list); sign in as `admin` / `admin`; the app bar shows PAHMA.
- [ ] Open the UI mockup (`./bmu open mockup`): the sign-in card starts with a Museum list of the mockup's museums, above the username. Choose one and sign in: the mockup shows that museum. The dashed "Mockup only" box no longer has a Tenant list.

## 10. One deployment for several museums: the deployment (90 minutes, mostly waiting)

Branch `feature/museum-deploy` (PR D of the multi-museum work; design: One deployment for several museums). The settings list the museums (`CSPACE_TENANTS`); Terraform gives each museum its own staging key and read-only account's secret, with S3 Bucket Keys off; `./bmu aws` checks the museums against the deployed ones, sets a museum's read-only account (`reader-secret <museum>`) and shows each museum in `status`; the worker has 1 vCPU. Claude ran the backend suite (with `deploy/aws.sh` against stand-ins for `aws`, `terraform`, `docker` and `curl`) and `fmt` on the Terraform code (with OpenTofu, since Terraform couldn't be downloaded). Claude could not run `terraform validate` or `terraform test`, build an image or reach AWS. personal-dev was destroyed after PR B, so this is a first deploy. Only PAHMA has a configuration: a second museum is tried with a temporary copy of it, `pahma2`, on the same PAHMA QA server.

**Before deploying**

- [ ] Locally, the `TF_DATA_DIR` checks in `deploy/README.md` ("Checking the Terraform code") pass, `terraform test` with 21 runs. Then CI on the pull request: `backend`, `frontend`, `dependencies` and `terraform` pass.
- [ ] If `deploy/environments/personal-dev.local.conf` sets `TENANT` or `CSPACE_URL`, replace them with one `CSPACE_TENANTS` line; otherwise `./bmu aws` stops with "not both".
- [ ] `aws sso login --profile bmu-personal`.

**personal-dev, one museum**

- [ ] `./bmu aws deploy`. The plan creates `aws_kms_key.staging["pahma"]` with the alias `alias/bmu-dev-staging-pahma`, the secret `bmu-dev/cspace-reader/pahma`, the worker's task definition with `cpu = 1024`, and `BMU_TENANTS`, `BMU_S3_KMS_KEY_IDS` and `BMU_READER_SECRET_IDS` in both task definitions. After the apply: "Careful: jobs run here create real records in each museum's CollectionSpace", then "pahma: https://pahma.qa.collectionspace.org".
- [ ] `./bmu aws status`: under "Museums", "pahma: https://pahma.qa.collectionspace.org" and "read-only account: NOT SET (./bmu aws reader-secret pahma)".
- [ ] `./bmu aws reader-secret` (no museum needed with one): it names pahma and its server; enter the QA reader account. `status` then reads "set, last changed <today>".
- [ ] Open the address and sign in with your PAHMA QA account: no Museum list; the header shows PAHMA.
- [ ] Add two files (thumbnails appear), submit, and let the job run at PAHMA's run time, or set `ALWAYS_RUN_TIME=true` in the `.local.conf` and deploy first. Finished jobs shows it completed. Watch `./bmu aws logs web` and `logs worker` for `AccessDenied` or `KMS` errors: those would mean a key or bucket policy refuses what the app does.
- [ ] Each file uses its museum's key, without a Bucket Key. While a draft has files: `aws s3api list-objects-v2 --profile bmu-personal --bucket <the staging bucket> --prefix staging/pahma/ --query 'Contents[].Key'` (`terraform output staging_bucket` after `./bmu aws init`, or the S3 console), then `aws s3api head-object --profile bmu-personal --bucket <bucket> --key <one key>`: `SSEKMSKeyId` is the key behind `alias/bmu-dev-staging-pahma` (`aws kms describe-key --profile bmu-personal --key-id alias/bmu-dev-staging-pahma --query KeyMetadata.Arn`) and there is no `"BucketKeyEnabled": true`.
- [ ] Optional: CloudTrail, Event history, Event source `kms.amazonaws.com`: each upload has a `GenerateDataKey` whose encryption context `aws:s3:arn` names the file.
- [ ] Sign in as an intern and open a draft open to interns: the languages list loads.

**A second museum (temporary)**

Since October 8 (Richard's decision): the second museum is UCJEPS, once section 11's local checks pass, and it stays in personal-dev; the removal test uses a throwaway `pahma2` instead.
- Adding, the reader secret, signing in and the key check: skip the `sed` step, list `ucjeps=https://ucjeps.qa.collectionspace.org` in `CSPACE_TENANTS`, read `ucjeps` wherever these steps say `pahma2`, and sign in to UCJEPS with your UCJEPS QA account. The image is clean, not `-dirty`.
- The server-change step: change UCJEPS's address, as written for `pahma2`, then put it back.
- The removal steps: run the `sed` step to make `pahma2`, add `pahma2=https://pahma.qa.collectionspace.org` to `CSPACE_TENANTS` (three museums), deploy, give it a draft, then follow the removal steps for `pahma2`. UCJEPS and PAHMA stay.

- [ ] Make the temporary museum (don't commit it): `sed -e 's/^key: pahma$/key: pahma2/' -e 's/^name: PAHMA$/name: PAHMA copy/' backend/bmu/tenants/pahma.yaml > backend/bmu/tenants/pahma2.yaml`. In `personal-dev.local.conf`: `CSPACE_TENANTS="pahma=https://pahma.qa.collectionspace.org pahma2=https://pahma.qa.collectionspace.org"`.
- [ ] `./bmu aws plan`: "Adding the museum pahma2 (https://pahma.qa.collectionspace.org)". The plan adds pahma2's key, alias and secret, and changes the bucket policy, the roles' policies and both task definitions. Nothing of pahma's is replaced.
- [ ] `./bmu aws deploy` (the image tag ends in `-dirty`). The sign-in page now starts with a Museum list: PAHMA and PAHMA copy.
- [ ] `./bmu aws reader-secret` is refused ("one of: pahma pahma2"); `./bmu aws reader-secret pahma2` sets pahma2's (the same QA reader account). `status` lists both museums, each "set".
- [ ] Sign in to PAHMA copy with your QA account. The header shows PAHMA copy, and PAHMA's jobs aren't listed. Add a file: `list-objects-v2 --prefix staging/pahma2/` shows it, and `head-object` shows pahma2's key (`alias/bmu-dev-staging-pahma2`).
- [ ] Server change refused: set pahma2 to `https://example.org` in `CSPACE_TENANTS`; `./bmu aws plan` stops with "'personal-dev' was deployed with pahma2 on https://pahma.qa.collectionspace.org, but its settings now say https://example.org". Put it back.
- [ ] Removal refused with unfinished jobs: keep the draft from above, take pahma2 out of `CSPACE_TENANTS`, and run `./bmu aws plan`: "pahma2 is no longer in the settings, but it has 1 unfinished job(s)". Nothing changes.
- [ ] Put pahma2 back, sign in to PAHMA copy, delete the draft. Take pahma2 out again: `./bmu aws plan` explains the removal and says "(./bmu aws deploy asks before removing it.)"; the plan destroys pahma2's key, alias and secret.
- [ ] `./bmu aws deploy`: type something else at "Type the museum's name (pahma2)": "Stopped; nothing was changed". Run it again and type `pahma2`. After the apply the sign-in page has no Museum list. In the KMS console, pahma2's key is "Pending deletion" (7 days).
- [ ] Delete `backend/bmu/tenants/pahma2.yaml`, and deploy once more so the image is clean (its tag no longer ends in `-dirty`).

**Then**

- [ ] Section 7 (the simulated CollectionSpace), as amended above.
- [ ] `./bmu aws pause` when you're done.

## 11. UCJEPS (60 minutes)

Branch `feature/ucjeps-tenant`. UCJEPS's configuration (`backend/bmu/tenants/ucjeps.yaml`) comes from the legacy BMU and UCJEPS's UI profile; parts of it can only be confirmed on UCJEPS QA (`https://ucjeps.qa.collectionspace.org`). Claude ran the backend suite (with `tests/test_ucjeps.py`) and the frontend type check and lint; Claude could not reach UCJEPS QA. These checks create real records on UCJEPS QA.

**Before starting, on UCJEPS QA**

- [ ] Create them first (none existed on October 8): the roles BMU_Staff, BMU_Intern and BMU_Reader (BMU_Reader with read permission only: Objects, Media, the Person and Organization authorities, vocabularies and the date parser; see deploy/README.md), BMU_Staff on your account, an intern account with BMU_Intern, and a read-only account with only BMU_Reader.

**The configuration against UCJEPS QA** (`scripts/check_cspace.py`). First, in the shell you'll use, so the password isn't shown, saved in a file or kept in the shell's history: `export CSPACE_URL=https://ucjeps.qa.collectionspace.org CSPACE_USER=<you>; read -rs -p "Password: " CSPACE_PASSWORD; export CSPACE_PASSWORD`. Run `unset CSPACE_PASSWORD` when done.

- [ ] `python scripts/check_cspace.py --tenant ucjeps --roles`: your BMU role is staff, with nothing missing.
- [ ] `... --tenant ucjeps --vocabularies`: the Person vocabulary `person`, and the Organization vocabularies `organization` and `institution`, exist.
- [ ] `... --tenant ucjeps --terms "urn:cspace:ucjeps.cspace.berkeley.edu:orgauthorities:name(institution):item:name(UniversityandJepsonHerbariaImageCollection1445039176532)'University and Jepson Herbaria Image Collection'"`: the Slide contributor exists.
- [ ] `... --tenant ucjeps --object <a specimen number, e.g. UC1107670> --show-object`: the Object record has `postToPublic` in `collectionobjects_ucjeps` (the sensitivity rule reads it).
- [ ] Optional, creates records: `... --tenant ucjeps --object <number> --create`: the Media record is created and linked, with Post to public = yes in UCJEPS's UI.

**Locally against UCJEPS QA**

- [ ] `./bmu down qa`, then `BMU_QA_TENANT=ucjeps BMU_ALWAYS_RUN_TIME=true ./bmu up qa`. The label reads "Local · UCJEPS QA"; sign in with your UCJEPS QA account; the header shows UCJEPS.
- [ ] Add files named after real specimens (`UC1107670.jpg`, `UC1107670_detail.jpg`): the object number is `UC1107670` for both. A name with a space shows "Fix filename".
- [ ] Handling offers Link to existing object, Create new object + link, Media only (no object) and Slide (no object). Slide fills the type Slide (Photograph), the copyright statement and the contributor University and Jepson Herbaria Image Collection, all marked as presets. The media type list is UCJEPS's (digital image, illustration, scanned photograph, slide (photograph) among them).
- [ ] Mark one document Restricted, then submit and let the job run. In UCJEPS's UI, the Media records have Post to public = yes, except the restricted one (no); each is linked to its specimen (Link) or has none (Slide); nothing is reported as an error.
- [ ] A document linked to a specimen with Post to public = no becomes a protected file (if QA has one): "specimen not posted to public", Restricted by default.
- [ ] As the intern: a draft open to interns checks its documents; the languages list loads.
- [ ] `./bmu down qa` when done (the next `./bmu up qa` without `BMU_QA_TENANT` is PAHMA again).

**Then** section 10's second museum in AWS, with UCJEPS.

## 12. Review fixes of 29 October 2026 (45 minutes)

Branch `fix/review-2026-10-29`. Claude ran both full suites (backend with the new `tests/test_lost_answers.py`, `tests/test_review_fixes_auth.py` and `tests/test_review_fixes_input.py`; frontend with lint, type check and tests). These checks need a browser, the simulated CollectionSpace (`./bmu up sim`, Demo tools on) or AWS.

**Lost answers and stopping (simulated CollectionSpace)**

- [ ] Demo tools, Slow (a few seconds per create). Submit a job of 3 documents, and while the first one's file is uploading run `./bmu down sim` then `./bmu up sim` (the worker gets SIGTERM). Within about 2 minutes the job is Failed, "worker stopped", with "SIGTERM" in the technical detail, not after the 5-minute heartbeat check. Reschedule: it completes, and Demo tools' CollectionSpace view shows one Media record and one Blob per document.
- [ ] A document whose step is shown as "sent, not confirmed" or "may have been saved" has no Delete button and can't be deleted with Delete selected.

**Roles and editing**

- [ ] Two browsers, the same draft: take it over in the second, then change a field in the first. The first shows that it's no longer editing; the field isn't changed for the second.
- [ ] Add files, and while they upload click New job (or open another draft). Back in the first draft, the documents whose uploads were stopped show Retry, none says "Upload failed" from the server, and Retry sends each file once.
- [ ] As `intern`, in a fix open to interns with one document: Delete is refused ("only staff can delete it"), and the job stays.
- [ ] As `limited` (no groups permission), with the job's group on: the bulk panel's Group list offers "No (leave out)"; "Yes" can't be chosen.

**Sign-in**

- [ ] Ten wrong passwords for one username, then the right one: "Too many failed sign-ins". Another username still signs in. After 15 minutes the first signs in again.

**In AWS (after `./bmu aws deploy`)**

- [ ] Deploy while a job runs: the worker log shows "stopping after the steps in progress", the job ends as worker stopped within 2 minutes, and `./bmu aws logs worker` has no AccessDenied.
- [ ] Sign in and use the editor for a few minutes as staff: no AccessDenied in `./bmu aws logs web` (the row writes are now DynamoDB transactions, and failed sign-ins are counted in the sessions table).

## 13. Review fixes, infrastructure (30 October 2026; 30 minutes in AWS)

Branch `fix/review-infra-2026-10-30`. Claude ran `terraform fmt`, `validate` and `test` (Terraform 1.16.5) and the backend suite; nothing was applied to AWS.

- [ ] `./bmu down all`, then `./bmu up sim`: the app opens at http://localhost:5173 and uploads work (the ports are now published on 127.0.0.1 only). From another computer on the same network, `http://<your Mac's address>:8000/api/health` doesn't answer.
- [ ] `./bmu aws plan`: the changes are the staging keys' policies, the load balancer's security group rule (unchanged port 80), and nothing is replaced.
- [ ] `./bmu aws deploy`: sign in, upload a JPEG and a TIFF (its thumbnail appears), submit, let the job run: no AccessDenied in `./bmu aws logs web` or `./bmu aws logs worker` (the staging keys now allow only the two roles, through S3).
- [ ] With your administrator sign-in, `aws s3 cp s3://<staging bucket>/staging/pahma/<a staged key> -` is refused (AccessDenied from KMS).
- [ ] Optional, with `WAF_ENABLED=true`: deploy, then 25 wrong sign-ins from one address within 5 minutes: after about 20 the page gets a 403 from CloudFront. It lifts within minutes.
- [ ] Optional, once there is a domain: set `ORIGIN_DOMAIN` and `ORIGIN_CERTIFICATE_ARN` (deploy/README.md, HTTPS to the load balancer), deploy, and check the app still opens.

## 14. The design document's review fixes (30 October 2026; 15 minutes)

Branch `docs/review-design-2026-10-30`. Claude ran the backend suite with `tests/test_review_fixes_design.py`. Section 7 of the review is mostly wording in `docs/design.md`; these are the checks for the code that came with it.

- [ ] Chunked uploads through the hosted CollectionSpace (review 7.14). With the QA sign-in in the shell as in section 11, `python scripts/check_cspace.py --tenant pahma --object <a test object number> --create`: "attach file (PUT media/{csid}/blob, chunked like the worker)" succeeds, and the Media record's blobCsid and Thumbnail are read back. If it fails where the earlier check passed, the worker's uploads fail on QA the same way: tell Claude.
- [ ] As `intern`, open the Drafts list where a staff-only draft has thumbnails: its expanded row and its preview show placeholders, not the images. Open the draft to interns: the images appear.
- [ ] Optional: in a fix, retry a failed upload, then let the fix expire (or set its `draftExpiresAt` in the past and wait for the sweep): the restored document shows "Upload failed" with Retry.

## 15. A 409, and the security headers (30 October 2026; 15 minutes)

Branch `fix/review-409-headers`. Claude ran the backend suite with `tests/test_review_fixes_409_headers.py`, and loaded the built app in Chromium under the new Content Security Policy (sign-in and every tab, no violations); it couldn't try uploads there.

- [ ] `./bmu up sim`, sign in, add a JPEG and a TIFF, submit and run a job: no "Refused to…" or "Content Security Policy" messages in the browser's console (the local dev server doesn't send the policy, so do this in AWS, below, too).
- [ ] In AWS after `./bmu aws deploy`: the response headers of the page (browser dev tools, Network) include `content-security-policy` with `connect-src 'self' https://…s3…amazonaws.com`, and uploads, thumbnails and a run work with no console errors.
- [ ] Demo tools, fail rule on `media` with status 409 for one file: that document fails with "CollectionSpace refused a request as a conflict", and the job's other documents still run.

## 16. The Selenium tests, bmut (29 October 2026; 15 minutes)

Branch `test/selenium-additional`. The first automated browser checks (`bmut/`, run by `./bmu test`; `bmut/README.md`), on a test stack of their own. They automate parts of sections 2, 2a, 2b and 2i; those steps can be ticked by a passing run instead of by hand.

Claude ran `./bmu test` with `./bmu up sim` running alongside: 15 passed, and the sim stack kept running. The suite found one bug, fixed on the branch: after a session ended, signing in again opened Create / edit job instead of the page you were on (section 2, Sign out and session end, step 2). Claude ran the frontend's lint, typecheck and Vitest (265 tests, one new) in Docker; Node isn't installed on the Mac.

- [ ] Section 2's session-end step by hand: delete the `bmu_session` cookie on Drafts, click Finished jobs, sign in again. Expect Finished jobs, not Create / edit job.

- [ ] With `./bmu up sim` running, run `./bmu test`. Expect every test to pass, and the sim stack at http://localhost:5173 untouched (still signed in, its drafts still there).
- [ ] `./bmu test -k sign_out --headed`: Chrome opens and you can watch the one test.
- [ ] Make a test fail on purpose (change an expected text in `bmut/tests/test_tabs.py`), run it: the report names a screenshot and the page's HTML in `bmut/.run/failures/`. Put the text back.
- [ ] `./bmu test-down` stops the test stack; `./bmu status` still shows sim running.

## 17. The Selenium tests in CI (29 October 2026; 10 minutes, then a few weeks)

Branch `ci/bmut`. Claude checked the workflow with actionlint and ran `./bmu test` on the Mac as CI will (`BMUT_PYTHON`), but couldn't run the CI job itself: it runs once the branch is pushed. On the way, about one run in five failed a sign-in on a fresh stack: a page moves the focus itself half a second after it loads (`putFocusNextTick`), and keys the test typed after that went into the wrong field. The tests now wait for that focus and check what they typed; three runs on fresh stacks and eight cold starts of the failing step then passed.

- [ ] On the pull request, the `bmut` job runs and passes. Note how long it took (the stack's build and start-up are most of it).
- [ ] A pull request that changes only a `.md` file shows `bmut` as skipped.
- [ ] Break a test on a scratch branch (change an expected text in `bmut/tests/test_tabs.py`), push it: the job fails, the log ends with each service's last lines in folded groups, and the run's artifacts hold `bmut-failures` with the screenshot. Delete the branch.
- [ ] After a few weeks of pull requests with no flaky `bmut` failure, make `bmut` a required check (Settings → Branches → the rule for `main`), and say so in `bmut/README.md`, the `ci.yml` comment and this item.

## 18. The Selenium tests: roles and the list tabs (29 October 2026; 15 minutes)

Branch `test/bmut-roles-and-lists`. Tests only: no change to the app. 31 more checks in `bmut/` (`bmut/README.md` lists them), automating most of sections 2c, 2i, 2j, 2k, 2l and 2m; those steps can be ticked by a passing run. Each file signs in once per user (`admin`, `limited`, `intern`), in a browser of its own, and works through its drafts as those people would; the queue tests pause the queue so their jobs wait in it.

Claude ran `./bmu test` on fresh stacks until three runs in a row passed: 46 tests, 3 to 3½ minutes of tests per run after the stack's start-up. Two things were found and fixed in the tests on the way. Every test as `intern` failed at first: Chrome's password manager knows `intern` / `intern` as a leaked password, and its "Change your password" bubble took the keys and clicks the test sent; the tests' browsers now run without the password manager. And one run in six failed the existing `test_name_a_job_and_add_files`: after a reload it read the job name before the page had filled it in; it now waits for it.

Still by hand, because the tests don't cover them: 2c's schedule settings, dragging, the "Sorted view" note, a running job's progress and Cancel run, deleting 20 documents at once, and dark mode; 2i's Demo tools "Sign in as" box; 2j step 6 (an intern losing access while editing); 2k's thumbnail, the Creator search, Language list and date preview as an intern, the `reader:` log lines and `bmureader` at sign-in; 2l's Show list counts and step 7, and the purple in dark mode; 2m's audit log.

Two things the tests showed, neither changed here:

- Take over: the first person's editor turns read-only at their next change (a refused save), not on its own; the test makes a change. Section 2c's step reads as if it happened at once. Say whether it should.
- An intern's "Submit for review…" tooltip in the editor reads "Fix or exclude the documents marked Needs fixing first" for one document too; the same button on a Drafts row counts them ("the document", "the 2 documents").

- [ ] On the pull request, the `bmut` job passes. Note how much longer it took than on earlier pull requests.
- [ ] `./bmu test -k roles --headed`: watch the intern's and admin's browsers work side by side.

## 19. The Selenium tests: the editor, Finished jobs and jobs that collide (29 October 2026; 15 minutes)

Branch `test/bmut-editor-finished-collisions`. Tests only: no change to the app. 22 more checks in `bmut/` (`bmut/README.md` lists them), automating most of what was left of sections 2a and 2b, and of 2d, 2g and 2n; those steps are marked above. Three new files, `test_editor.py`, `test_finished_jobs.py` and `test_queue_collisions.py`, and one test added to `test_drafts_and_queue.py`. The runs that fail on purpose get their failures from Demo tools ("Make CollectionSpace fail"), each naming one file; a failed browser upload, which Demo tools can only slow down, comes from Chrome blocking the stack's S3 address.

Claude ran `./bmu test` three times in a row, each on a fresh stack: 68 tests passed each time, about 5 minutes of tests per run after the stack's start-up (46 before). The new tests passed first time apart from their own expectations, which the runs corrected (what a job reads when one document fails, and "1 done · 1 partial").

Still by hand, because the tests don't cover them: 2a's 30-document expand-all scroll, Save draft, dark mode and the large-draft paging speed; 2d's paging in the results, the run history's order over several runs, Reschedule opening the job, and dark mode; 2g's drag and drop, other jobs keeping their places after Reorder, and that nothing was created for the document that failed; 2n's preview buttons other than Edit.

Three things the tests showed, none changed here:

- In the read-only preview of a draft someone else is editing (the locked banner), Submit job is on: the job name and the documents are off, Submit isn't. Say whether it should be off too.
- "Change selected documents": Apply to all applies at once. Section 2a's step expects a confirmation; there is none now (Delete selected still asks).
- A job in which one document fails and the others are done reads "Needs attention", whichever step failed; "Failed" is only for a run that stopped as a whole, such as CollectionSpace refusing the sign-in. Section 2d's "make a job need attention and one fail" needs a failure of that kind (Demo tools: `media` with 401).

- [ ] On the pull request, the `bmut` job passes. Note how long it took.
- [ ] `./bmu test -k test_queue_collisions --headed`: watch the intern's Job queue flag job A after admin's "Move anyway", without a reload.

## 20. The shared simulator, the fakecspace package (30 October 2026; 15 minutes, on a network with IPv4 to PyPI)

Branch `feature/fakecspace-package`. The simulated CollectionSpace is now the `fakecspace` package (0.2.0, from PyPI), in
place of `backend/fakecspace`, in its own image for every local stack as in AWS. It starts empty and its image seeds the
BMU's samples; PAHMA's tenant ID there is 14. The backend tests and the Selenium tests cover the app; these checks are
of the stacks and the Demo tools. Rebuild first: `./bmu down sim`, then `./bmu up sim` (the build downloads the package,
so not on the T-Mobile hotspot, which gives no IPv4).

- [ ] **1. It starts seeded.** `./bmu logs sim fakecspace` shows Uvicorn on port 8180, and Demo tools' sample objects
  list the 14 Objects (12-2001 to 12-2003 sensitive, 3-1004 deleted). `curl localhost:8180/_fake/state` shows one
  Media record, 15-1234.
- [ ] **2. Sign in** as `admin` (staff), `intern` (intern) and `reader` (refused), with Sign in as and by typing.
- [ ] **3. A job runs.** Submit a job with `15-1240_1.jpg` and `1-2345_a.jpg`: Completed, with the Media records,
  Blobs and Relations in `/_fake/state`.
- [ ] **4. Make CollectionSpace fail.** In Demo tools, add `upload` with 413, Times 1, "in job runs", mentioning
  `1-2345`: the list shows "upload → 413 if “1-2345”, 1 of 1 left". Run a job with that file: its document fails with
  "File too large", and the editor's checks were unaffected. Add one "everywhere", then Clear failures.
- [ ] **5. Resets seed the samples again.** Reset the simulator, then Reset everything: each time the sample objects are
  the 14 again and a job with `15-1240_1.jpg` finds its Object.
- [ ] **6. The commands.** The commands box's simulator lines (copy them) add a rule, reset and seed, run as shown.
- [ ] **7. AWS, with the simulator** (`SIMULATED_CSPACE=true`, an environment you can redeploy): `./bmu aws deploy`
  builds the simulator's image from the package and the service starts. There are no Demo tools there, so: a job with
  `15-1240_1.jpg` finds its Object (the samples were seeded), and an intern's checks work (the `bmureader` secret).
- [ ] On the pull request, the `bmut` job passes: the Selenium tests run against the package's simulator.

## 21. Shared mode, with Serena (30 October 2026; 20 minutes)

Branch `feature/shared-simulator`. `./bmu up shared` uses the simulator shared with Serena (cspace-fakecspace's
`compose.shared.yml`, merged in its PR #6: a clone of its `main` beside this one, `git pull` first) in place of one
of its own. Serena's side is its testing checklist section 53. Start with `docker compose -p fakecspace-shared down`.

- [ ] **1. It starts the simulator.** `./bmu up shared` says "Starting the shared simulator from ../cspace-fakecspace",
  then the BMU is up at http://localhost:5673 with the label "Local · simulator shared with Serena". `./bmu status`
  lists `shared`.
- [ ] **2. Seeded.** Demo tools' sample objects list the 14 Objects. `./bmu up shared` again says the simulator is
  already running, and the objects are still 14 (not 28).
- [ ] **3. A job runs.** A job with `15-1240_1.jpg`: Completed, and `curl -s localhost:8680/_fake/media` lists its
  Media record with a Blob.
- [ ] **4. No reset.** Demo tools have no "Reset simulated CollectionSpace", and say why under the Reset box. Reset
  everything's question says the simulator isn't reset; after it, the job is gone but its Media record is still in
  `localhost:8680/_fake/media`.
- [ ] **5. Through Serena.** `./serena up shared` (cspace-media-server) says the simulator is already running. In
  Serena's admin app, Manual refresh for PAHMA, "Make one from the simulator": the BMU's record is listed. Apply, then
  the image comes out of Serena.
- [ ] **6. Down.** `./bmu down shared` says the shared simulator is still running; `./bmu up sim` still works beside it.

## 22. CI's sign-in to ECR Public (31 October 2026; 15 minutes, signed in to the personal account)

Branch `feature/ecr-public-sign-in`. The `bmut` job signs in to ECR Public before pulling base images
(deploy/README.md, "CI's sign-in to ECR Public").

- [ ] **1. Create the role.** `aws sso login --profile bmu-personal`, then `./bmu aws ci-role`: the plan creates the
  role `bmu-ci-ecr-public-pull`, its policy and (unless the account has one) GitHub's OIDC provider, and nothing else.
  Type `yes`. It prints a `gh variable set ECR_PUBLIC_ROLE_ARN ...` command.
- [ ] **2. Set the variable.** Run that command; `gh variable list` shows `ECR_PUBLIC_ROLE_ARN`.
- [ ] **3. CI signs in.** Re-run the pull request's `bmut` job: "Sign in to AWS for ECR Public" and "Sign in to ECR
  Public" pass, and the images build.
- [ ] **4. Nothing more.** In the IAM console, the role's trust names only this repository, and its one policy has
  only `ecr-public:GetAuthorizationToken` and `sts:GetServiceBearerToken`.
- [ ] **5. Again changes nothing.** `./bmu aws ci-role` a second time: "No changes".

## 23. Stage 2 in UC Berkeley's account: an existing VPC, the load balancer front door and the deployer policy (8 November 2026)

Branches `feature/vpc-devqa-deployer-policy` and `feature/stage2-alb-front-door`. `ucb-qa` deploys into Operations'
dev/QA VPC (deploy/README.md, "Deploying into an existing VPC") with `FRONT_DOOR=alb` ("Stage 2: UC Berkeley's
account"), as `rtl-BmuQaDeployer` (deploy/iam/README.md). Steps 1 and 2 in the personal account (15 minutes); the
rest in UC Berkeley's account once Operations has created the role (about an hour, plus waiting for Operations' two
DNS records). Every command from `cd ~/dev/src/rtl/cspace-bulk-media-uploader`, on a clean checkout of `main`
(`REQUIRE_CLEAN=true`).

Already checked (8 November 2026, with Serena's stage 2 profile): vpc-devqa's S3 gateway endpoint is `available`, the
app subnets' route table is among its route tables, and its policy is AWS's default (allow everything). So the tasks'
own writes reach the staging bucket through it, as the upload rule (BQ31) needs.

- [x] **1. The personal environment keeps CloudFront.** `aws sso login --profile bmu-personal`, then
  `./bmu aws plan`. Expected: the CloudFront distribution, function and VPC origin and the prefix list rule are
  listed as "has moved to …[0]", and nothing is destroyed or replaced (the load balancer's security group keeps its
  description). Anything to be destroyed or replaced: stop and note it. (Passed, before November 9, 2026.)
- [x] **2. The parts.** `python3 deploy/iam/split-policy.py`. Expected: three parts, each at most 6,144 characters,
  written to `deploy/iam/out/` (`git status` doesn't list them), and no `cloudfront` in any. These are the files
  Operations attaches. (Passed, before November 9, 2026.)
- [x] **3. The settings.** `ucb-qa.local.conf` as in `ucb-qa.conf`'s comments: the VPC, its private and
  public subnets, `CREATE_GATEWAY_ENDPOINTS=false`, `DOMAIN_NAME` from Operations and `ALLOWED_CIDRS` (campus and
  VPN). `git status` lists no change. (9 November 2026: made from Serena's `ucb-stage2.local.conf`, the same account,
  VPC and subnets, with `ALLOWED_CIDRS` from its `ADMIN_CIDRS`, four ranges. With `ACCOUNT_ID` already set there, step
  4 doesn't ask to confirm the account: it checks the signed-in account against it.)
- [x] **4. The certificate.** Sign in to IAM Identity Center through the session that `bmu-qa-deploy`'s
  `source_profile` uses (`aws sso login --sso-session <name>`; `aws sso login --profile bmu-qa-deploy` fails, because
  that profile takes the role from another profile rather than signing in itself), and check the role:
  `aws sts get-caller-identity --profile bmu-qa-deploy` ends in `assumed-role/rtl-BmuQaDeployer/…`. Then
  `./bmu aws deploy --env ucb-qa`. Expected: it creates the image repository and the certificate, prints the
  validation record (`CNAME _….bmu-qa.… _….acm-validations.aws.`) and stops, with nothing built. Send the record to
  Operations (the Ops ask). Once they've added it, `aws acm list-certificates --profile bmu-qa-deploy --region
  us-west-2` shows the certificate `ISSUED` (minutes to an hour). (9 November 2026: created the state bucket, the
  repository, its lifecycle policy and the certificate, 3 resources, no `AccessDenied`; printed the record and
  stopped. `ISSUED` within minutes of Operations adding it. The profile needs `duration_seconds` between 900 and
  3600: AWS refuses a shorter session.)
- [x] **5. Plan and deploy.** `./bmu aws deploy --env ucb-qa` again. Expected, in the plan: no `aws_cloudfront_*`
  resources and no `aws_vpc`, `aws_subnet`, `aws_internet_gateway` or `aws_route_table`; the load balancer
  `internal = false` in the public subnets; one listener, HTTPS on 443 (no port 80); one security group rule per
  allowed range, on 443; the web ACL (`scope = "REGIONAL"`), its association and its log group
  `aws-waf-logs-bmu-qa`; the bucket policy's `UploadsOnlyFromTheAllowedAddressesOrTheVpc`. After `yes` it
  finishes and prints the load balancer's DNS name. On `AccessDenied`, note the action and resource here, stop, and
  fix the policy (a pull request, then the changed part to Operations). (9 November 2026: 58 to add, 0 to change,
  0 to destroy; everything above as expected, the VPC and subnets only read; the listener uses
  `ELBSecurityPolicy-TLS13-1-2-2021-06`. "Apply complete! Resources: 58 added", no `AccessDenied`, so the deployer
  policy needed no change. The deploy's own health check answered `000`, as expected before the name's record.)
- [x] **6. The name's record.** Operations points `DOMAIN_NAME` at the load balancer's DNS name (a CNAME). Then
  `./bmu aws reader-secret pahma --env ucb-qa` (PAHMA QA's read-only account). (9 November 2026: the record was in
  within the hour; the reader secret set.) Before the record exists, the app can be checked through the load
  balancer under the real name, with a valid certificate:
  `curl --connect-to <DOMAIN_NAME>:443:<load balancer's DNS name>:443 https://<DOMAIN_NAME>/api/health`.
- [x] **7. Access from campus and the VPN.** From campus, and from home on the VPN: `https://<DOMAIN_NAME>` opens
  the sign-in page; the certificate is valid for the name; `curl -sS -D - -o /dev/null https://<DOMAIN_NAME>/api/health`
  answers `200` and shows `strict-transport-security`, `content-security-policy` and `x-frame-options: DENY`
  (`curl -sI` sends `HEAD`, which `/api/health` answers with `405`, though with the same headers).
  `http://<DOMAIN_NAME>` doesn't connect (no port 80). (9 November 2026, on the VPN: all as expected; port 80 timed
  out after 10 seconds.)
- [x] **8. Access from off campus.** Off the VPN (a phone's hotspot): `https://<DOMAIN_NAME>` times out (the
  security group drops it; no 403 page as with CloudFront). (9 November 2026: timed out.)
- [x] **9. The app, as Serena's #197 taught.** Sign in with a PAHMA QA staff account, add a file to a job (the
  browser's upload to S3 works from campus), check its thumbnail appears (the tasks' own write, through the
  endpoint), submit and run it (real records on PAHMA QA); sign in as an intern and open a draft (the languages list
  loads). Watch `./bmu aws logs web --env ucb-qa` and `worker` for `AccessDenied`. To hide the requests every open
  page repeats: `./bmu aws logs web --env ucb-qa 2>&1 | grep --line-buffered -vE '"GET /api/(jobs|schedule|health)[^"]*" 200 '`.
  (9 November 2026: two jobs of 5 and 4 documents, JPEG and TIFF, uploaded, thumbnails stored, submitted and run:
  9 Media records with their files, their Relations and one new Object, every CollectionSpace call `200` or `201`.
  An intern made a 7-document draft, its checks and the languages list worked through the read-only account, and
  sent it for review. No `AccessDenied` or traceback in either log. A thumbnail asked for in the second after a
  document's upload or run answers `404` until it exists; the page shows it at the next refresh.)
- [ ] **10. Uploads refused from off campus.** With a job open from campus, note a presigned upload (the browser's
  network panel, the POST to the staging bucket); the same upload from off campus (or, simpler: the BMU used from off
  campus can't load at all, step 8) is refused by S3 with `AccessDenied`. Optional: it shows that the bucket rule,
  not only the load balancer, keeps uploads to the allowed ranges. (9 November 2026: not done; step 8 passed.)
- [x] **11. The WAF's logs.** In CloudWatch Logs, `aws-waf-logs-bmu-qa` has entries for steps 7 to 9; an entry's
  `httpRequest` shows the path, the query string `REDACTED` and no `cookie` value. In the WAF console, the web ACL's
  sampled requests show the managed rule sets' matches as `COUNT`. After a week of logs, decide on
  `WAF_MANAGED_RULES=block` (BQ28). (9 November 2026, read with `aws logs tail aws-waf-logs-bmu-qa --since 4h`:
  2,801 entries, all `ALLOW`; every query string and every cookie header `REDACTED`. The only managed rule matched
  was the common rule set's `SizeRestrictions_BODY`, 8 times, as `COUNT`: thumbnails and saves over 8 KB, which
  `waf.tf` keeps at count whatever `WAF_MANAGED_RULES` says.)
- [x] **12. Nothing else in the VPC.** In the VPC console, filtered by the tag `project=bmu`: only the BMU's security
  groups. Its route tables are unchanged. (9 November 2026, with `aws ec2 describe-security-groups`,
  `describe-vpc-endpoints` and `describe-route-tables` filtered by the tag: the security groups `bmu-qa-alb`,
  `bmu-qa-web` and `bmu-qa-worker`, and no endpoints or route tables.)
- [ ] **13. Destroy** (only if that's the plan before acceptance). `./bmu aws destroy --env ucb-qa`: it finishes,
  and the VPC console no longer lists anything tagged `project=bmu`. A later deploy reuses the validation record but
  has a new load balancer: Operations repoints the name (BQ32). (9 November 2026: not done; `ucb-qa` stays up for
  acceptance.)

Found on the way (9 November 2026): status badges need a description on hover and focus (#141), and the review and
checks badges in Drafts and the Job queue are too long for the row.

## 24. The deployer rehearsal (8 November 2026; about 2 hours, in the personal account)

Branches `feature/deployer-rehearsal` and `feature/stage2-alb-front-door`. The BMU deployed into a VPC like Operations',
as a role with only the deployer policy, with stage 2's front door (deploy/README.md, "Rehearsing the deploy in your
own account"), so that missing permissions are found before Operations attaches it. Every command from
`cd ~/dev/src/rtl/cspace-bulk-media-uploader`. Note here every `AccessDenied`: the action, the resource, and the fix
to `deploy/iam/bmu-deployer-policy.json`.

- [x] **0. The rehearsal's name (BQ23).** A name under the Route 53 zone Serena's rehearsal used, in the personal
  account (check the zone still exists: `aws route53 list-hosted-zones --profile bmu-personal`). Put it in
  `personal-rehearsal.local.conf` as `DOMAIN_NAME=…` (never in the committed `.conf`).
- [x] **1. What Operations provides.** `aws sso login --profile bmu-personal`, then
  `./bmu aws rehearsal-vpc --env personal-rehearsal`. The first time it asks to confirm the account (yes). Expected:
  Terraform's plan lists a VPC, four subnets, an internet gateway, an Elastic IP, a NAT gateway, two route tables and
  four associations, the role `rehearsal-devqar-deployer`, and three policies `rehearsal-devqar-deployer-1` to `-3` with
  their attachments; nothing named `bmu-`. Type `yes`. It saves `VPC_ID`, `APP_SUBNET_IDS` and `LB_SUBNET_IDS`, then
  prints a `[profile bmu-rehearsal-deploy]` section.
- [x] **2. The deployer's profile.** Add that section to `~/.aws/config`. Check:
  `aws sts get-caller-identity --profile bmu-rehearsal-deploy` shows an `assumed-role/rehearsal-devqar-deployer/…` ARN.
- [x] **3. The certificate, as the deployer.** `./bmu aws deploy --env personal-rehearsal`. Expected: the image
  repository and the certificate are created, the validation record is printed, and it stops. Add the record in
  Route 53 by hand, as Operations will (a CNAME, the name and value printed). Wait for `ISSUED`.
- [x] **4. Deploy as the deployer.** `./bmu aws deploy --env personal-rehearsal` again. Expected: the image is built
  and pushed, Terraform plans the BMU with no CloudFront, no VPC or subnets of its own, two gateway endpoints
  (`CREATE_GATEWAY_ENDPOINTS=true`), the internet-facing load balancer, the WAF and the simulator, and after `yes`
  (5 to 10 minutes) it prints the load balancer's DNS name. Add the name's record in Route 53 (a CNAME to it). Note
  any `AccessDenied` (then step 5). In particular: the certificate's tags, the web ACL and its association
  (`SetWebAcl`), the WAF's logging (log delivery, the resource policy), and the gateway endpoints on the VPC's route
  table.
- [x] **5. If something was denied.** Add the permission to the policy, run
  `./bmu aws rehearsal-vpc --env personal-rehearsal` (as administrator; the plan changes only the policies), then step 4
  again; Terraform continues where it stopped. `python3 deploy/iam/split-policy.py --check` still fits in three parts.
- [x] **6. The app, as Serena's #197 taught.** From this computer: `https://<DOMAIN_NAME>` opens; sign in as
  `admin`, make a job with a file (its thumbnail appears: the tasks' write through the endpoint), submit it (it runs
  at once: `ALWAYS_RUN_TIME=true`), see it finish; sign in as `intern` and open a draft (the languages list loads).
  Meanwhile `./bmu aws logs web --env personal-rehearsal` and `worker` show no `AccessDenied` (the app's own roles,
  not the deployer's). From a phone off your network, the name times out.
- [x] **7. Day-to-day commands as the deployer.** `./bmu aws status` (it shows the front door), `pause`, `resume`,
  `allow-my-ip` and `logs fakecspace`, each with `--env personal-rehearsal`: none is denied.
- [x] **8. Destroy as the deployer.** `./bmu aws destroy --env personal-rehearsal`: it finishes, with no
  `AccessDenied` (the certificate is deleted with the registry). Delete the name's record in Route 53; keep the
  validation record if the rehearsal may run again (it stays valid for the same name).
- [x] **9. Remove the rehearsal.** `aws sso login --profile bmu-personal` if needed, then
  `./bmu aws rehearsal-vpc --env personal-rehearsal destroy`; type `yes`. `personal-rehearsal.local.conf` no longer
  has `VPC_ID`, `APP_SUBNET_IDS` or `LB_SUBNET_IDS`; the `[profile bmu-rehearsal-deploy]` section can be removed from
  `~/.aws/config`.
- [x] **10. The result.** If the policy changed, commit it (with these notes) before the ask goes to Operations.

Result (8 November 2026, personal-rehearsal, from `main` after PR 128): **no `AccessDenied` anywhere, so the deployer
policy needs no change** (step 5 was not needed). `rehearsal-vpc` added 21 resources, none named `bmu-`, and the
deployer's profile showed the assumed role. The first deploy as the deployer added 5 (the two image repositories, a
lifecycle policy, and the certificate with its tags); the certificate was `ISSUED` about a minute after the validation
record was added. The second added 66, among them the web ACL, its association and logging (with the log resource
policy), both gateway endpoints, the internet-facing load balancer with its HTTPS listener (TLS 1.3 policy), and the
simulator with its service discovery; the load balancer's security group allowed only this computer's address. In the
app, admin and intern signed in, the languages list loaded, every thumbnail was written through the endpoint, the job
ran to Completed, and a phone off the network timed out. The web and worker logs had no `AccessDenied`. `status`,
`pause`, `resume`, `allow-my-ip`, `logs fakecspace`, `destroy` and `rehearsal-vpc … destroy` all finished, and the
local conf lost its network IDs. One file of the first job was marked "Upload failed" although it was in S3: an app
race on `uploaded` (409), not a permission; fixed in PR 131 and checked in section 25. Two slips, for next
time: the name's record was first created with a placeholder as its value (a runnable command must never hold one),
and macOS then kept the bad answer cached until `dscacheutil -flushcache`.

## 25. Uploads that finish together, on real DynamoDB (8 November 2026; 10 minutes, on an AWS environment)

Branch `fix/uploaded-transaction-conflict`. Found in section 24: three files added at once, and one
`POST …/rows/<n>/uploaded` answered 409 while the others answered 200, so the page marked a file that was in S3
"Upload failed" (Retry then worked). Real DynamoDB cancels a transaction whose items another write is changing at
that moment (`TransactionConflict`): each `uploaded` saves its row in a transaction that checks the job item, and the
editor's `/check` saves the rows' checks meanwhile. moto never does this, so the tests simulate it
(`backend/tests/test_upload_races.py`); only an AWS environment shows the real thing.

- [x] **1. Many files at once.** On an AWS environment (DynamoDB, not the local one), sign in as `admin`, make a job and
  add 10 to 20 small JPEGs in one go. Expected: every document ends "Uploaded", none "Upload failed".
- [x] **2. The log.** `./bmu aws logs web --env <env>`: no `uploaded` answered 409. Lines
  `put_row: job … row …: transaction conflict (…), trying again` may appear (the cancellation reasons, for the
  record); a `transaction cancelled (…)` line means a save gave up: note its reasons here.
- [x] **3. Twice more**, with a different number of files, since the race depends on timing.

Result (8 November 2026, personal-rehearsal, image `c80d900`, after PR 131): four jobs of 25, 13, 22 and 24 files.
Every document ended "Uploaded", and all 84 `uploaded` requests answered 200, none 409. Three saves met a conflict
and went through on the retry, each logged as `transaction conflict (None,TransactionConflict), trying again`: the
reasons follow the transaction's order, so the row's own put was fine (`None`) and the check on the job item met
another transaction on that item (`TransactionConflict`). Two came during the uploads (row 17 of the first job, row
11 of the second). The third came during the fourth job's first `/check`, before any upload: the check's own row
saves also check the job item, so they can conflict with each other too, and the retry covers them. There was no `transaction cancelled` line. The cause found in section 24 is confirmed, and the retry
works.

## 26. No Route 53 in the deployer policy (8 November 2026; nothing to do until the next rehearsal or UC Berkeley deploy)

Branch `fix/deployer-policy-no-route53`. The deployer policy no longer has any Route 53 or Cloud Map permission; the
rehearsal's role gets them inline from `deploy/iam/bmu-simulator-dns-policy.json`, for the simulator only. CI checks
both (`backend/tests/test_deploy.py`, `deploy/terraform/rehearsal/tests`). What only a real run shows:

- [ ] **1. The parts.** `python3 deploy/iam/split-policy.py`. Expected: three parts, each at most 6,144 characters;
  `grep -lE '"(route53|servicediscovery):[A-Z]' deploy/iam/out/*.json` lists none (the region Deny's `route53:*`
  exemption doesn't match).
- [ ] **2. The next rehearsal** (section 24): `./bmu aws rehearsal-vpc --env personal-rehearsal` shows the role's
  inline policy `rehearsal-<env>-simulator-dns`, and the deploy, with the simulator, ends with no `AccessDenied`.
- [ ] **3. The UC Berkeley deploy** (section 23, steps 4 and 5): no `AccessDenied` on `route53:` or
  `servicediscovery:` (it creates neither: there is no simulator there).

## 27. Thumbnails kept per session (9 November 2026; 15 minutes, on your local stack, then on ucb-qa)

Branch `fix/thumbnail-cache-per-session`. The browser keeps a thumbnail only under the signed-in session's key (`k` in
the thumbnail's address), and signing out clears the browser's cache of the BMU. CI checks the server's answers
(`test_the_browser_keeps_a_thumbnail_only_under_its_sessions_key`) and the address (`thumbs.test.ts`); only a real
browser shows what it does with them. Restart first: `./bmu down sim`, then `./bmu up sim`, and open
http://localhost:5173 in Chrome, with the developer tools open on the Network panel.

- [x] **1. The address and the answer.** Sign in as `admin`, make a job with two JPEG files and run it (Run now), then
  open Finished jobs and expand it. Expected: each thumbnail's request is `…/thumbnail?v=…&k=<16 characters>`, and its
  answer has `cache-control: private, max-age=300`. Collapse and expand the job again: the requests show
  "(memory cache)" or "(disk cache)".
- [x] **2. Sign-out.** Choose Sign out. Expected: the `POST /api/logout` answer has `clear-site-data: "cache"`.
- [x] **3. The next user.** Within 5 minutes, sign in as `intern` (the job is staff only) and expand the same job in
  Finished jobs. Expected: grey tiles, not the images; the requests carry a different `k` and answer `404`
  (`./bmu logs sim web` shows them). Since section 28, the intern's page doesn't ask for these thumbnails at all: grey tiles, and
  no thumbnail requests.
- [x] **4. Back as staff.** Sign out, sign in as `admin` again: the thumbnails show, with a new `k`.
  (Steps 1 to 4: passed, 9 November 2026.)
- [x] **5. On ucb-qa,** after `./bmu aws deploy --env ucb-qa`: repeat steps 1 to 3 with a PAHMA QA staff account and an
  intern's, as on November 9 (section 23). Expected: the intern sees no thumbnails of the staff-only jobs.
  (9 November 2026, image `afa14f8`: the intern saw grey tiles; every thumbnail request carried the session's `k` and
  answered `404`. `POST /api/logout` answers with `clear-site-data: "cache"`.)

## 28. No repeated requests for thumbnails that are refused (9 November 2026; 10 minutes, on your local stack)

Branch `fix/thumbnail-requests`. Found on ucb-qa on November 9 (section 27, step 5): an intern who expanded two
staff-only jobs in Finished jobs rightly got grey tiles, but the page asked for the same thumbnails again at every
refresh (every 4 seconds), each answered `404`, filling the web log. Now a thumbnail that failed is asked for again only
when its document changes (a new `v`) or its file reaches CollectionSpace, and an intern's page doesn't ask for
thumbnails the server always refuses an intern: those of a staff-only job, and those of documents already in
CollectionSpace. Staff see what they saw before. CI checks each case in `thumbs.test.ts`; only a real browser shows the
requests it makes.

Start clean: in a terminal,

```bash
cd ~/dev/src/rtl/cspace-bulk-media-uploader && ./bmu down sim && ./bmu up sim
```

then open http://localhost:5173 in Chrome, with the developer tools open on the Network panel and its filter set to
`thumbnail`. In a second terminal, follow the web app's log, showing only thumbnail requests:

```bash
cd ~/dev/src/rtl/cspace-bulk-media-uploader && ./bmu logs sim web | grep --line-buffered thumbnail
```

- [x] **1. Staff, as before.** Sign in as `admin`, make a job with two JPEG files and one TIFF, and leave it staff only.
  Open Drafts and expand the job. Expected: the three thumbnails show; the TIFF's may take a refresh or two (5 seconds
  each) while it is made, and appears once it is stored. Choose Run now and wait for the job to finish. Open Finished
  jobs and expand it. Expected: the three thumbnails show, now CollectionSpace's derivatives, each requested once.
  (9 November 2026: passed. Steps 1 to 4 were run in Claude's built-in browser, its network log and the web log
  standing in for Chrome's Network panel. Each thumbnail was requested once in Drafts and once in Finished jobs. After
  the run the TIFF shows a "TIF" tile, not an image: the simulated CollectionSpace serves the TIFF itself as its
  derivative, which a browser can't show, where real CollectionSpace makes a JPEG. It wasn't requested again.)
- [x] **2. An intern, staff-only job.** Sign out and sign in as `intern`. Open Finished jobs, expand the job, and wait 20
  seconds (five refreshes). Expected: grey tiles; the Network panel shows no thumbnail requests, and the log in the
  second terminal shows no new lines.
  (9 November 2026: passed: grey tiles; no thumbnail requests in 24 seconds, and no new lines in the log.)
- [x] **3. An intern, a draft open to interns.** As `intern`, make a draft with one JPEG file, then open Drafts and
  expand it. Expected: its thumbnail shows, requested from the web app (a staged file, which the server gives an intern
  of a draft open to interns; the editor shows the one made in the browser instead).
  (9 November 2026: passed: one request, answered `200`, and the thumbnail shows.)
- [x] **4. An intern, after a run.** Sign out, sign in as `admin`, open the intern's draft, and choose Submit job, then
  Run now from Job queue. Once it has finished, sign out and sign in as `intern` again, open Finished jobs and expand
  that job (open to interns, its file now in CollectionSpace). Expected: a grey tile, no thumbnail request in the
  Network panel and no new line in the log, for as long as the page stays open.
  (9 November 2026: passed: a grey tile; no thumbnail request in 25 seconds, and no new line in the log.)
- [ ] **5. A failed thumbnail isn't asked for again.** Tick Disable cache in the Network panel. As `admin`, expand the
  first job in Finished jobs. In the Network panel, right-click one thumbnail request and choose Block request URL,
  then collapse and expand the job. Expected: that tile is grey and its request shows as blocked once; wait 20 seconds:
  it isn't requested again. Remove the block (Network request blocking panel) and untick Disable cache.

## 29. The sign-in hint names what signs in (9 November 2026; 2 minutes, on ucb-qa's profile)

Branch `fix/aws-sign-in-hint`. When `./bmu aws` finds no sign-in it names the command to run. It used to name
`aws sso login --profile <the environment's profile>`, which fails for a profile that takes a role from another
(`source_profile`), such as `bmu-qa-deploy` ("Missing the following required SSO configuration values"). It now
follows `source_profile` and names that profile's SSO session (`--sso-session`), or the profile itself when it has
SSO settings of its own. CI checks the cases against a sample configuration
(`test_the_sign_in_hint_names_what_signs_in`); this checks it against your own `~/.aws/config`.

- [x] **1. Signed out.** Sign out of IAM Identity Center, then ask for ucb-qa's status:

  ```bash
  cd ~/dev/src/rtl/cspace-bulk-media-uploader && aws sso logout && ./bmu aws status --env ucb-qa
  ```

  Expected: "Not signed in to AWS for 'ucb-qa'. Run: aws sso login --sso-session <your session's name>", not
  `--profile bmu-qa-deploy`. (Before section 30's fix, cached role credentials could hide a sign-out for up to an
  hour.)
  (12 November 2026: passed: it named `aws sso login --sso-session berkeley`. The first try, with the role's
  credentials still cached, ended in a Terraform init error instead of the hint; after `rm -rf ~/.aws/cli/cache` it
  gave the hint. That gap is section 30.)
- [x] **2. The named command works.** Run the command it named, then `./bmu aws status --env ucb-qa` again. Expected:
  the environment's status, with no sign-in message.
  (12 November 2026: passed: it signed in, and the status showed ucb-qa with web 1 of 1 and worker 1 of 1, image
  `8fd4737`.)
- [x] **3. A personal profile.** `aws sso logout`, then `./bmu aws status` (personal-dev). Expected: it names
  `bmu-personal`'s session (`aws sso login --sso-session …`, or `--profile bmu-personal` if that profile has its own
  SSO settings), and that command signs you in.
  (12 November 2026: passed: it named `aws sso login --sso-session bmu-personal`, which signed in; personal-dev showed
  "Not deployed".)

## 30. Signed out, with the role's credentials still cached (12 November 2026; 3 minutes, on ucb-qa's profile)

Branch `fix/aws-sso-token-check`. The AWS CLI keeps the credentials of a role it took (`source_profile`, as
`bmu-qa-deploy` does) in `~/.aws/cli/cache` for up to an hour, and `aws sso logout` leaves them. `./bmu aws` used to
take a passing `aws sts get-caller-identity` as signed in, and Terraform, which doesn't read that cache, then failed
in `terraform init` ("failed to read cached SSO token file"). It now also checks for the SSO token Terraform starts
from (`~/.aws/sso/cache`): there and not expired, or renewable with its refresh token. CI checks the cases with a fake
`aws` (`test_cached_role_credentials_without_an_sso_token_are_not_signed_in`); this checks it with the real one.

- [ ] **1. Signed out, credentials cached.** Sign in, use the profile once so the CLI caches the role's credentials,
  sign out, and ask for ucb-qa's status within the hour:

  ```bash
  cd ~/dev/src/rtl/cspace-bulk-media-uploader && aws sts get-caller-identity --profile bmu-qa-deploy >/dev/null && aws sso logout && ./bmu aws status --env ucb-qa
  ```

  Expected: "Not signed in to AWS for 'ucb-qa'. Run: aws sso login --sso-session <your session's name>", and no
  Terraform error. (Section 29's step 1 no longer needs the cached credentials to expire.)
- [ ] **2. Signed in.** Run the command it named, then `./bmu aws status --env ucb-qa`. Expected: the environment's
  status, with no sign-in message.

## 31. Settings in SSM Parameter Store (13 November 2026; about 40 minutes, in the personal account)

Branch `feature/settings-ssm`, the deploy pipeline's second pull request (design: Deploys, BP4). An environment with
`SETTINGS=ssm` keeps its settings in SSM Parameter Store in its own account instead of in the files on one computer,
so that whoever deploys it, and later the pipeline's build, reads the same values. The account's administrator puts
them there with `./bmu aws settings push`; the deployer only reads them, and its policy gains exactly that
(`SettingsRead`, and `ssm:DescribeParameters`). CI checks the commands with a stand-in `aws`
(`backend/tests/test_aws_script.py`); this checks them, and the deployer policy, with the real one.

It uses `personal-rehearsal`, whose deployer role has only the deployer policy, as Operations attaches it. Nothing is
deployed: the steps make the rehearsal's VPC and deployer role, which `./bmu aws status` needs, then delete them. Its
NAT gateway costs a few cents an hour while it exists, so do it in one sitting.

**Before you start.** In your BMU clone, on this branch (`git switch feature/settings-ssm && git pull`), with
`deploy/environments/personal-rehearsal.local.conf` from section 24 (it holds `ACCOUNT_ID` and `DOMAIN_NAME`; check
with `ls deploy/environments/personal-rehearsal.local.conf`). Every command runs from the clone's top folder. Two
profiles: `bmu-personal`, the account's administrator, and `bmu-rehearsal-deploy`, the deployer. `./bmu aws` picks
the right one for each command (`ADMIN_PROFILE` and `AWS_PROFILE` in `personal-rehearsal.conf`).

**Terraform's output.** Steps 1 and 9 run Terraform, so their commands pipe it through `tfsummary` (the team's tool,
`_team/tools/tfsummary` in rtl-team-notes, on your `PATH`). `tfsummary` shortens the plan to one line per resource
and masks account numbers, addresses and secrets. Terraform's "Enter a value:" prompt still shows, so you review
the plan and type `yes` as usual. `tee` saves the summary to a file in `/tmp` named for the step, which you can hand
to Claude to read instead of pasting it. `tfsummary` also keeps the whole output, masked, in `~/.cache/tfsummary/` and
prints that file's name at the end. `set -o pipefail` keeps the command's own exit status through the pipe.

Sign in once:

```bash
aws sso login --profile bmu-personal
```

- [ ] **1. The deployer role, with the new policy.** As the administrator, make the rehearsal's VPC and deployer
  role:

  ```bash
  set -o pipefail; ./bmu aws rehearsal-vpc --env personal-rehearsal 2>&1 | tfsummary | tee /tmp/bmu-checklist-31-step1.txt
  ```

  Expected: the summary of Terraform's plan lists the VPC, its subnets and NAT gateway, the role
  `rehearsal-devqar-deployer` and its three policies, as in section 24, step 1. Type `yes`. It saves `VPC_ID`,
  `APP_SUBNET_IDS` and `LB_SUBNET_IDS` in the `.local.conf`, and says "The deployer's profile bmu-rehearsal-deploy is
  in ~/.aws/config." (from section 24). The last line is `tfsummary`'s, naming the full log. The summary is in
  `/tmp/bmu-checklist-31-step1.txt`. (If it prints a `[profile bmu-rehearsal-deploy]` section instead, its role ARN
  is masked there: `aws configure get role_arn --profile bmu-rehearsal-deploy` shows what `~/.aws/config` has, and the
  role is `rehearsal-devqar-deployer` in this account.) Check that the policy that was made includes the new
  statement:

  ```bash
  python3 deploy/iam/split-policy.py --check
  ```

  Expected: three parts, the third ending in `KeyAlias, SettingsRead`.
- [ ] **2. Switched on, with nothing in SSM yet.** Add the setting to the `.local.conf`, then ask for the status, as
  the deployer:

  ```bash
  echo 'SETTINGS=ssm' >> deploy/environments/personal-rehearsal.local.conf
  ```

  ```bash
  ./bmu aws status --env personal-rehearsal
  ```

  Expected: "'personal-rehearsal' keeps its settings in SSM (SETTINGS=ssm), and account <your account> has none
  under /bmu-devqar/settings/." and, on the next line, "The account's administrator puts them there from
  deploy/environments/personal-rehearsal.conf and deploy/environments/personal-rehearsal.local.conf: ./bmu aws
  settings push --env personal-rehearsal". No `AccessDenied`: the deployer may list the parameters.
- [ ] **3. Put them there, as the administrator.**

  ```bash
  ./bmu aws settings push --env personal-rehearsal
  ```

  Expected: "From deploy/environments/personal-rehearsal.conf and deploy/environments/personal-rehearsal.local.conf to
  SSM, account <your account>, /bmu-devqar/settings/:", then one `+` line per setting, among them `ACCOUNT_ID`,
  `ALLOWED_CIDRS`, `SIMULATED_CSPACE=true`, `ENV_LABEL=AWS · personal-rehearsal · simulated CollectionSpace`,
  `FRONT_DOOR=alb`, `DOMAIN_NAME`, `VPC_ID`, `APP_SUBNET_IDS`, `LB_SUBNET_IDS` and `REHEARSAL=true`; none for
  `AWS_PROFILE`, `ADMIN_PROFILE`, `SETTINGS` or `REQUIRE_CLEAN`. Then "Write these to SSM? The next deploy uses them.
  [y/N]". Type `y`. Expected: "Done. ./bmu aws plan --env personal-rehearsal shows what they change." Run the same
  command again. Expected: "SSM already has these settings for 'personal-rehearsal' (account <your account>,
  /bmu-devqar/settings/)." and no question.
- [ ] **4. What SSM holds.** As the administrator, list the parameters' names and types (not their values):

  ```bash
  aws ssm get-parameters-by-path --path /bmu-devqar/settings --profile bmu-personal --query 'Parameters[].[Name,Type]' --output text
  ```

  Expected: one line per setting from step 3, each `String` (not `SecureString`: none is a secret).
- [ ] **5. The deployer reads them.**

  ```bash
  ./bmu aws status --env personal-rehearsal
  ```

  Expected: "Settings: SSM Parameter Store, /bmu-devqar/settings/ (./bmu aws settings show)", then "Not deployed
  (./bmu aws deploy).", with no `AccessDenied` and no "differ" note.
- [ ] **6. The deployer can't write them.** First through `./bmu aws`:

  ```bash
  ./bmu aws allow-my-ip --env personal-rehearsal
  ```

  Expected: "'personal-rehearsal' keeps its settings in SSM. To allow <this computer's address>/32, set
  ALLOWED_CIDRS="…" in deploy/environments/personal-rehearsal.local.conf; the account's administrator then runs
  ./bmu aws settings push --env personal-rehearsal, and the next deploy applies it." (If this computer's address is
  already allowed, it says "<address>/32 is already allowed." instead.) Nothing changes. Then try to write a setting
  directly as the deployer, which the policy must refuse:

  ```bash
  aws ssm put-parameter --profile bmu-rehearsal-deploy --name /bmu-devqar/settings/ENV_LABEL --type String --value test --overwrite
  ```

  Expected: "An error occurred (AccessDeniedException) when calling the PutParameter operation: User: …
  rehearsal-devqar-deployer/… is not authorized to perform: ssm:PutParameter …".
- [ ] **7. When the files here disagree.** Give the files another label, then look:

  ```bash
  echo 'ENV_LABEL="AWS · rehearsal · files"' >> deploy/environments/personal-rehearsal.local.conf
  ```

  ```bash
  ./bmu aws settings show --env personal-rehearsal
  ```

  Expected: every setting from step 3, and "ENV_LABEL=AWS · personal-rehearsal · simulated CollectionSpace   (the
  files here: AWS · rehearsal · files)". Then `./bmu aws status --env personal-rehearsal` starts with "Note: the
  files on this computer differ from SSM in ENV_LABEL; SSM's are used (./bmu aws settings show)." Take the line out
  again:

  ```bash
  sed -i '' '/^ENV_LABEL=/d' deploy/environments/personal-rehearsal.local.conf
  ```

- [ ] **8. Delete refuses while something is deployed.** The rehearsal's VPC still is:

  ```bash
  ./bmu aws settings delete --env personal-rehearsal
  ```

  Expected: "'personal-rehearsal' is still deployed (bmu/devqar/rehearsal.tfstate): destroy it first (./bmu aws
  destroy, then rehearsal-vpc destroy for a rehearsal)." Nothing is deleted.
- [ ] **9. Clean up.** Delete the VPC and the deployer role (Terraform asks; type `yes`). With `SETTINGS=ssm` it also
  removes `VPC_ID`, `APP_SUBNET_IDS` and `LB_SUBNET_IDS` from SSM:

  ```bash
  set -o pipefail; ./bmu aws rehearsal-vpc destroy --env personal-rehearsal 2>&1 | tfsummary | tee /tmp/bmu-checklist-31-step9.txt
  ```

  Expected: "This deletes the rehearsal's VPC, NAT gateway and deployer role in account <masked>. Terraform asks
  first.", the summary of what Terraform destroys, and after `yes`, "Done. The [profile bmu-rehearsal-deploy] section
  in ~/.aws/config can go too." (keep it for the next rehearsal). The summary is in
  `/tmp/bmu-checklist-31-step9.txt`.

  Then delete the settings (type `personal-rehearsal` when asked). Expected: "This deletes <n> settings of
  'personal-rehearsal' in SSM, …", "The files on this computer stay.", then "Done.":

  ```bash
  ./bmu aws settings delete --env personal-rehearsal
  ```

  Last, switch the environment back to its files, and check the setting is gone (expected: `0`):

  ```bash
  sed -i '' '/^SETTINGS=ssm$/d' deploy/environments/personal-rehearsal.local.conf && grep -c '^SETTINGS=' deploy/environments/personal-rehearsal.local.conf
  ```

## Not tests, but still open

- The design doc's "For Richard to address" list (from the October 3 comparison of the doc with the prototype).
