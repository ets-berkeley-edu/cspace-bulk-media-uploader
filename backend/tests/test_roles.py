"""BMU_Staff and BMU_Intern (design: Roles): who can sign in, and what an intern may do."""
from test_flow import _second_user, new_job

STAFF_ONLY = ("Only users with the BMU_Staff role can do this. Interns can create drafts and edit the drafts that are "
              "open to interns.")
FILE = {"name": "15-1234_2.jpg", "size": 3, "type": "image/jpeg"}


def _sign_in(api, user):
    return api.post("/api/login", json={"username": user, "password": user})


# ---- signing in ----------------------------------------------------------------------------------------------
def test_a_user_with_neither_role_cannot_sign_in(api, services):
    r = _sign_in(api, "reader")  # can read everything in CollectionSpace, but has no BMU role
    assert r.status_code == 403 and r.json()["detail"] == {
        "code": "no_role",
        "message": "Your CollectionSpace account doesn't have the BMU_Staff or BMU_Intern role, which the BMU needs. "
                   "Contact your CollectionSpace administrator if you think this is wrong."}
    assert services.storage.sessions.scan()["Items"] == []  # no session, so no password kept
    assert api.get("/api/me").status_code == 401


def test_staff_need_the_permissions_the_role_exists_for(api, fake, services):
    r = _sign_in(api, "newstaff")  # BMU_Staff, but the account can only read
    d = r.json()["detail"]
    assert r.status_code == 403 and d["code"] == "account"
    assert d["message"] == ("Your CollectionSpace account has the BMU_Staff role, but it can't create Media records, update "
                            "Media records or create relations. The BMU needs that to create Media records. "
                            "Contact your CollectionSpace administrator if you think this is wrong.")
    assert services.storage.sessions.scan()["Items"] == []
    for resource, letters, said in [("media", "CUL", "read Media records"), ("relations", "RL", "create relations"),
                                    ("collectionobjects", "CL", "read Objects"), ("personauthorities", "", "read Person authorities"),
                                    ("orgauthorities", "", "read Organization authorities"), ("vocabularies", "", "read vocabularies"),
                                    ("structureddates", "", "read dates (the date parser)")]:
        fake.perm_overrides["admin"] = {resource: letters}
        r = _sign_in(api, "admin")
        assert r.status_code == 403 and f"but it can't {said}. " in r.json()["detail"]["message"], (resource, r.text)
    fake.perm_overrides["admin"] = {"collectionobjects": "RL", "groups": "RL"}  # creating Objects and groups isn't required
    assert _sign_in(api, "admin").status_code == 200


def test_an_intern_signs_in_with_no_permissions_at_all(api):
    r = _sign_in(api, "intern")
    assert r.status_code == 200 and r.json()["role"] == "intern"
    assert not any(r.json()["perms"][k] for k in ("media", "mediaUpdate", "relations", "objects", "readObjects", "readMedia"))


def test_a_user_with_both_roles_is_staff(api, fake):
    fake.role_overrides["admin"] = ["ROLE_15_BMU_INTERN", "ROLE_15_BMU_STAFF"]
    assert _sign_in(api, "admin").json()["role"] == "staff"
    fake.role_overrides["intern"] = ["ROLE_15_BMU_INTERN", "ROLE_15_BMU_STAFF"]  # staff, so the permissions are required
    assert _sign_in(api, "intern").json()["detail"]["code"] == "account"


def test_a_session_from_before_roles_must_sign_in_again(api, login, services):
    login()
    key = services.storage.sessions.scan()["Items"][0]["PK"]
    services.storage.sessions.update_item(Key={"PK": key}, UpdateExpression="REMOVE #r", ExpressionAttributeNames={"#r": "role"})
    assert api.get("/api/me").status_code == 401
    assert services.storage.get_session(key) is None


# ---- what a job remembers ----------------------------------------------------------------------------------------
def test_a_job_keeps_who_created_it_and_starts_open_to_interns_only_for_an_intern(api, login, services):
    login()
    mine = api.post("/api/jobs", json={"name": "Staff"}).json()
    assert (mine["createdBy"], mine["createdByRole"], mine["internOpen"]) == ("admin", "staff", False)
    theirs = _second_user(services, "intern").post("/api/jobs", json={"name": "Intern"}).json()
    assert (theirs["createdBy"], theirs["createdByRole"], theirs["internOpen"]) == ("intern", "intern", True)


# ---- interns: drafts that are open to interns, and nothing else ---------------------------------------------------
def test_an_intern_creates_and_edits_drafts_that_are_open_to_interns(api, login, services, fake):
    intern = _second_user(services, "intern")
    job = intern.post("/api/jobs", json={"name": "Photos"}).json()["id"]
    assert intern.patch(f"/api/jobs/{job}", json={"name": "Photos, box 3"}).status_code == 200
    assert intern.post(f"/api/jobs/{job}/files", json={"files": [FILE]}).status_code == 200
    assert intern.post(f"/api/jobs/{job}/check").status_code == 200  # the checks run, with what the intern's account can read
    assert intern.post(f"/api/jobs/{job}/save").status_code == 200
    assert intern.post(f"/api/jobs/{job}/close").status_code == 200
    # another intern picks it up; so can a staff member, and it stays open to interns
    fake.role_overrides["newstaff"] = ["ROLE_15_BMU_INTERN"]
    other = _second_user(services, "newstaff")
    assert other.post(f"/api/jobs/{job}/open").json()["editingBy"] == "newstaff"
    assert other.post(f"/api/jobs/{job}/close").status_code == 200
    login()
    assert api.post(f"/api/jobs/{job}/open").status_code == 200 and api.post(f"/api/jobs/{job}/close").status_code == 200
    assert services.storage.get_job(job)["internOpen"] is True
    assert intern.delete(f"/api/jobs/{job}").status_code == 200  # never ran: an intern may delete it


def test_an_intern_cannot_touch_a_staff_only_draft_or_a_submitted_job(api, login, add_uploaded, worker, services, fail_on):
    login()
    draft = new_job(api)
    n = add_uploaded(draft, ["15-1234_1.jpg"])[0]["n"]
    api.post(f"/api/jobs/{draft}/close")
    queued = new_job(api)
    add_uploaded(queued, ["12-5678_1.jpg"])
    assert api.post(f"/api/jobs/{queued}/schedule").status_code == 200
    failed = new_job(api)
    add_uploaded(failed, ["3-1001_1.jpg"])
    fail_on("upload", status=413)
    assert api.post(f"/api/jobs/{failed}/schedule").status_code == 200
    services.storage.update_job(queued, {"queuePos": 10 ** 12})  # run the other one
    worker.tick()
    assert services.storage.get_job(failed)["status"] == "NeedsAttention"
    before = services.storage.get_row(draft, n)

    intern = _second_user(services, "intern")
    for r in [intern.post(f"/api/jobs/{draft}/open"), intern.post(f"/api/jobs/{draft}/open", json={"takeOverSince": 1}),
              intern.delete(f"/api/jobs/{draft}")]:
        assert r.status_code == 403 and r.json()["detail"] == "This draft is for staff only, so an intern can't edit or delete it.", r.text
    for r in [intern.post(f"/api/jobs/{draft}/schedule"), intern.post(f"/api/jobs/{queued}/edit"), intern.post(f"/api/jobs/{failed}/fix"),
              intern.delete(f"/api/jobs/{queued}"), intern.delete(f"/api/jobs/{failed}"),
              intern.post(f"/api/jobs/{queued}/run-now", json={"on": True}), intern.post("/api/schedule/pause", json={"reason": "x"})]:
        assert r.status_code == 403 and r.json()["detail"] == STAFF_ONLY, (r.request.method, r.request.url, r.text)
    # not being its editor, an intern can't change a staff-only draft's documents either
    for r in [intern.patch(f"/api/jobs/{draft}", json={"name": "x"}), intern.post(f"/api/jobs/{draft}/files", json={"files": [FILE]}),
              intern.patch(f"/api/jobs/{draft}/rows/{n}", json={"description": "x"}), intern.delete(f"/api/jobs/{draft}/rows/{n}"),
              intern.post(f"/api/jobs/{failed}/rows/1/replace-file", json=FILE)]:
        assert r.status_code == 409, (r.request.method, r.request.url, r.text)
    assert {services.storage.get_job(j)["status"] for j in (draft, queued, failed)} == {"Draft", "Queued", "NeedsAttention"}
    # viewing works: the lists, a job, its checks (shown to the intern, not saved), the schedule, the catalog
    assert intern.get("/api/jobs").status_code == 200 and intern.get(f"/api/jobs/{draft}").status_code == 200
    assert intern.post(f"/api/jobs/{draft}/check").status_code == 200
    assert intern.post(f"/api/jobs/{failed}/check").status_code == 200
    assert services.storage.get_row(draft, n) == before
    assert intern.get("/api/schedule").status_code == 200 and intern.get("/api/failures").status_code == 200
    assert intern.get("/api/queue/collisions").status_code == 200


def test_an_intern_takes_over_from_an_intern_but_not_from_staff(api, login, services, fake):
    intern = _second_user(services, "intern")
    job = intern.post("/api/jobs", json={"name": "Shared"}).json()["id"]  # the intern has it open
    fake.role_overrides["newstaff"] = ["ROLE_15_BMU_INTERN"]
    other = _second_user(services, "newstaff")
    locked = other.post(f"/api/jobs/{job}/open")
    assert locked.status_code == 409 and locked.json()["detail"]["editingBy"] == "intern"
    since = locked.json()["detail"]["editingSince"]
    assert other.post(f"/api/jobs/{job}/open", json={"takeOverSince": since}).json()["editingBy"] == "newstaff"
    login()  # a staff member takes it over from the intern
    since = api.post(f"/api/jobs/{job}/open").json()["detail"]["editingSince"]
    assert api.post(f"/api/jobs/{job}/open", json={"takeOverSince": since}).json()["editingBy"] == "admin"
    r = intern.post(f"/api/jobs/{job}/open", json={"takeOverSince": services.storage.get_job(job)["editingSince"]})
    assert r.status_code == 403 and r.json()["detail"] == "A staff member is editing this draft. Only staff can take it over."
    assert services.storage.get_job(job)["editingBy"] == "admin"
    api.post(f"/api/jobs/{job}/close")
    assert intern.post(f"/api/jobs/{job}/open").status_code == 200  # nobody has it open now


def test_an_intern_edits_but_does_not_delete_a_draft_that_has_run(api, login, add_uploaded, worker, services, fail_on):
    intern = _second_user(services, "intern")
    job = intern.post("/api/jobs", json={"name": "Ran once"}).json()["id"]
    intern.post(f"/api/jobs/{job}/close")
    login()
    assert api.post(f"/api/jobs/{job}/open").status_code == 200
    add_uploaded(job, ["15-1234_1.jpg"])
    fail_on("upload", status=413)
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200  # back in Drafts, still open to interns
    api.post(f"/api/jobs/{job}/close")
    assert services.storage.get_job(job)["internOpen"] is True
    assert intern.post(f"/api/jobs/{job}/open").status_code == 200
    r = intern.delete(f"/api/jobs/{job}")
    assert r.status_code == 403 and r.json()["detail"] == "This job has already run, so only staff can delete it. You can still edit it."
    intern.post(f"/api/jobs/{job}/close")
    assert api.delete(f"/api/jobs/{job}").status_code == 200


def test_a_staff_member_made_an_intern_loses_staff_actions_at_once(api, login, add_uploaded, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    fake.role_overrides["admin"] = ["ROLE_15_BMU_INTERN"]  # changed in CollectionSpace after signing in
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 403 and r.json()["detail"] == STAFF_ONLY
    assert api.get("/api/me").json()["role"] == "intern"  # the session follows


# ---- Open to interns / Staff only, and Hand over to staff ---------------------------------------------------------
def _audit(services, kind):
    return [a["detail"] for a in services.storage.list_audit("pahma") if a["type"] == kind]


def test_staff_change_a_draft_between_open_to_interns_and_staff_only(api, login, services):
    login()
    job = new_job(api)
    api.post(f"/api/jobs/{job}/close")
    intern = _second_user(services, "intern")
    assert intern.post(f"/api/jobs/{job}/open").status_code == 403
    r = api.post(f"/api/jobs/{job}/intern-access", json={"open": True})
    assert r.status_code == 200 and r.json()["internOpen"] is True
    assert api.post(f"/api/jobs/{job}/intern-access", json={"open": True}).status_code == 200  # already so: nothing to do
    assert intern.post(f"/api/jobs/{job}/open").json()["editingBy"] == "intern"
    # staff only again, while the intern has it open: the intern's editing ends at once
    assert api.post(f"/api/jobs/{job}/intern-access", json={"open": False}).json()["internOpen"] is False
    j = services.storage.get_job(job)
    assert "editingSession" not in j and "editingBy" not in j
    r = intern.patch(f"/api/jobs/{job}", json={"name": "x"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_editing"
    assert intern.post(f"/api/jobs/{job}/open").status_code == 403
    assert _audit(services, "Intern access changed") == ["Made “Test job” staff only.", "Opened “Test job” to interns."]  # newest first


def test_staff_only_does_not_end_a_staff_members_editing(api, login, services):
    login()
    job = new_job(api)
    api.post(f"/api/jobs/{job}/intern-access", json={"open": True})
    assert api.post(f"/api/jobs/{job}/intern-access", json={"open": False}).status_code == 200
    assert services.storage.get_job(job)["editingBy"] == "admin"


def test_an_intern_hands_a_draft_over_to_staff_and_cannot_take_it_back(api, login, services, fake):
    intern = _second_user(services, "intern")
    job = intern.post("/api/jobs", json={"name": "Ready"}).json()["id"]
    r = intern.post(f"/api/jobs/{job}/intern-access", json={"open": False})  # from the editor, with the draft open
    assert r.status_code == 200 and r.json()["internOpen"] is False and not r.json().get("editingBy")
    assert _audit(services, "Intern access changed") == ["Handed “Ready” over to staff."]
    for r in [intern.post(f"/api/jobs/{job}/intern-access", json={"open": True}), intern.post(f"/api/jobs/{job}/open"),
              intern.delete(f"/api/jobs/{job}")]:
        assert r.status_code == 403, r.text
    login()  # staff give it back
    assert api.post(f"/api/jobs/{job}/intern-access", json={"open": True}).status_code == 200
    assert intern.post(f"/api/jobs/{job}/open").status_code == 200
    # an intern can't hand over a draft another intern is editing, nor change a staff-only draft, nor open one to interns
    fake.role_overrides["newstaff"] = ["ROLE_15_BMU_INTERN"]
    other = _second_user(services, "newstaff")
    r = other.post(f"/api/jobs/{job}/intern-access", json={"open": False})
    assert r.status_code == 409 and "intern is editing this draft" in r.json()["detail"]
    mine = new_job(api)
    assert other.post(f"/api/jobs/{mine}/intern-access", json={"open": True}).status_code == 403
    assert services.storage.get_job(mine)["internOpen"] is False


def test_intern_access_is_set_on_drafts_only(api, login, add_uploaded):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    r = api.post(f"/api/jobs/{job}/intern-access", json={"open": True})
    assert r.status_code == 409 and "this is set on drafts" in r.json()["detail"]


# ---- Submit from the Drafts list --------------------------------------------------------------------------------------
def test_staff_submit_a_draft_nobody_has_open_and_the_audit_names_who_prepared_it(api, login, add_uploaded, services):
    intern = _second_user(services, "intern")
    job = intern.post("/api/jobs", json={"name": "Box 3"}).json()["id"]
    intern.post(f"/api/jobs/{job}/close")
    login("limited")  # a staff member tidies it up
    assert api.post(f"/api/jobs/{job}/open").status_code == 200
    add_uploaded(job, ["15-1234_1.jpg"])
    assert api.post(f"/api/jobs/{job}/save").status_code == 200
    api.post(f"/api/jobs/{job}/close")
    login()  # another staff member submits it from the Drafts list, without opening it
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 200 and r.json()["status"] == "Queued" and r.json()["scheduledBy"] == "admin"
    assert "editingSession" not in services.storage.get_job(job)
    assert _audit(services, "Submitted") == ["Submitted “Box 3” with 1 documents. Created by intern (intern); last saved by limited."]


def test_a_refused_submit_from_the_list_leaves_the_draft_in_nobodys_editor(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0777_1.jpg"])  # links to an object that doesn't exist: needs fixing
    api.post(f"/api/jobs/{job}/close")
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 409 and r.json()["detail"]["message"] == "1 documents need fixing first."
    j = services.storage.get_job(job)
    assert j["status"] == "Draft" and "editingSession" not in j
    empty = new_job(api)
    api.post(f"/api/jobs/{empty}/close")
    assert api.post(f"/api/jobs/{empty}/schedule").status_code == 409  # nothing to run
    assert "editingSession" not in services.storage.get_job(empty)


def test_a_draft_someone_is_editing_cannot_be_submitted_by_another(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])  # admin still has it open
    r = _second_user(services, "limited").post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 409 and r.json()["detail"] == {"code": "locked", "message": "admin is editing this draft, so it can't be submitted now."}
    assert services.storage.get_job(job)["editingBy"] == "admin"
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200  # its editor submits it, as before


# ---- Move to Drafts ---------------------------------------------------------------------------------------------------
def test_move_to_drafts_takes_a_job_out_of_the_queue_without_opening_it(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    assert _second_user(services, "intern").post(f"/api/jobs/{job}/to-drafts").status_code == 403
    r = api.post(f"/api/jobs/{job}/to-drafts")
    assert r.status_code == 200 and r.json()["status"] == "Draft" and not r.json().get("editingBy")
    assert services.storage.get_credential(job) is None  # its saved sign-in is deleted, as with Edit
    assert _audit(services, "Moved to Drafts") == ["Took “Test job” out of the queue; its saved sign-in was deleted."]
    assert api.post(f"/api/jobs/{job}/to-drafts").status_code == 409  # no longer queued
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200  # and it can go straight back
    assert api.post(f"/api/jobs/{job}/edit").json()["editingBy"] == "admin"  # Edit still opens it
    assert _audit(services, "Moved to Drafts")[0] == "Took “Test job” out of the queue to edit it; its saved sign-in was deleted."
