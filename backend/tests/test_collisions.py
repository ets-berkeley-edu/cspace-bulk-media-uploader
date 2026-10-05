"""Jobs that collide in the queue (design: Jobs that collide in the queue): a job that runs first can change
CollectionSpace so that a later job's document fails. The checks compare a job with the jobs ahead of it; a
scheduler is warned before a change to the order makes a document fail; and the queue can be reordered to avoid it."""
from bmu import schedule as sched
from test_flow import _checks, _second_user, new_job

MISSING = "20-0501"  # an object number the simulated CollectionSpace doesn't have


def _job(api, add_uploaded, name, file, handling):
    job = new_job(api, name)
    row = add_uploaded(job, [file])[0]
    r = api.patch(f"/api/jobs/{job}/rows/{row['n']}", json={"handling": handling})
    assert r.status_code == 200, r.text
    return job, row["n"]


def _queued(api, add_uploaded, name, file, handling):
    job, n = _job(api, add_uploaded, name, file, handling)
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 200, r.text
    return job, n


def _row(api, job, n):
    return next(r for r in api.post(f"/api/jobs/{job}/check").json()["rows"] if r["n"] == n)


def _blocks(api, job):
    return api.post(f"/api/jobs/{job}/check").json()["counts"]["block"]


# ---- at Submit and in the editor -------------------------------------------------------------------------------
def test_two_jobs_that_create_the_same_object_the_second_must_be_fixed(api, login, add_uploaded, worker):
    login()
    first, _ = _queued(api, add_uploaded, "First batch", f"{MISSING}.jpg", "create")
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "create")
    blocks = _checks(_row(api, second, n), "block")
    assert len(blocks) == 1 and "Job “First batch”, ahead of this one in the job queue, creates object 20-0501" in blocks[0]
    assert "choose “Link to object (create if missing)”" in blocks[0] and f"({MISSING}.jpg)" in blocks[0]
    r = api.post(f"/api/jobs/{second}/schedule")
    assert r.status_code == 409 and r.json()["detail"]["rows"] == [n]
    # the fix the message offers: link to the object the first job creates
    api.patch(f"/api/jobs/{second}/rows/{n}", json={"handling": "linkorcreate"})
    assert _checks(_row(api, second, n), "block") == []
    assert api.post(f"/api/jobs/{second}/schedule").status_code == 200
    assert worker.tick() and worker.tick()
    steps = {}
    for job in (first, second):
        j = api.get(f"/api/jobs/{job}").json()
        assert j["job"]["status"] == "Completed", j
        steps[job] = j["rows"][0]["result"]["steps"]
    # one Object: the first job created it, the second found it and linked to it
    assert steps[first]["createObject"]["s"] == "done"
    assert steps[second]["findOrCreateObject"]["found"] is True
    assert steps[second]["findOrCreateObject"]["csid"] == steps[first]["createObject"]["csid"]


def test_create_if_missing_ahead_also_creates_the_object(api, login, add_uploaded):
    login()
    _queued(api, add_uploaded, "First batch", f"{MISSING}.jpg", "linkorcreate")
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "create")
    assert any("creates object 20-0501" in t for t in _checks(_row(api, second, n), "block"))
    assert api.post(f"/api/jobs/{second}/schedule").status_code == 409


def test_create_ahead_of_create_if_missing_is_fine_and_so_are_two_that_link_or_create(api, login, add_uploaded):
    login()
    _queued(api, add_uploaded, "First batch", f"{MISSING}.jpg", "create")
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "linkorcreate")
    assert _checks(_row(api, second, n), "block") == []
    assert api.post(f"/api/jobs/{second}/schedule").status_code == 200
    third, n = _job(api, add_uploaded, "Third batch", f"{MISSING}_c.jpg", "linkorcreate")
    assert _checks(_row(api, third, n), "block") == []
    assert api.post(f"/api/jobs/{third}/schedule").status_code == 200


def test_the_same_identification_number_in_an_earlier_job_is_a_warning(api, login, add_uploaded):
    login()
    first, _ = _queued(api, add_uploaded, "First batch", f"{MISSING}.jpg", "create")
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "linkorcreate")
    warns = _checks(_row(api, second, n), "warn")
    assert any("Job “First batch”, ahead of this one in the job queue, also has a document with ID 20-0501" in t
               and "Both Media records would be created" in t for t in warns)
    assert api.post(f"/api/jobs/{second}/schedule").status_code == 200  # a warning doesn't stop Submit
    # the first job, which runs first, is told nothing
    assert api.post(f"/api/jobs/{first}/check").json()["counts"] == {"block": 0, "warn": 0}


def test_once_the_first_job_has_run_collectionspace_itself_says_the_object_exists(api, login, add_uploaded, worker):
    login()
    _queued(api, add_uploaded, "First batch", f"{MISSING}.jpg", "create")
    assert worker.tick()
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "create")
    blocks = _checks(_row(api, second, n), "block")
    assert len(blocks) == 1 and "already exists in CollectionSpace" in blocks[0] and "First batch" not in blocks[0]


# ---- changing the queue's order ----------------------------------------------------------------------------------
def _pair(api, add_uploaded):
    """"Creates it" queued first, "Links or creates" second, for the same new object number: fine in this order."""
    creates, _ = _queued(api, add_uploaded, "Creates it", f"{MISSING}.jpg", "create")
    links, _ = _queued(api, add_uploaded, "Links or creates", f"{MISSING}_b.jpg", "linkorcreate")
    return creates, links


def test_a_scheduler_is_warned_before_a_move_makes_a_document_fail(api, login, add_uploaded, services):
    login()  # admin is a BMU scheduler
    creates, links = _pair(api, add_uploaded)
    r = api.post(f"/api/jobs/{links}/move", json={"toIndex": 0})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "would_fail" and len(d["problems"]) == 1
    assert d["message"] == ("This would make 1 document fail when the queue runs: “20-0501.jpg” in “Creates it”: "
                            "“Links or creates” would create object 20-0501 first.")
    assert d["problems"][0] == {"job": creates, "name": "Creates it", "n": 1, "file": "20-0501.jpg", "other": links,
                                "otherName": "Links or creates", "object": "20-0501"}
    # nothing changed, and nothing was written to the audit log
    order = [j["id"] for j in api.get("/api/jobs").json()["jobs"] if j["status"] == "Queued"]
    assert sorted(order, key=lambda i: services.storage.get_job(i)["queuePos"]) == [creates, links]
    assert not [a for a in services.storage.list_audit("pahma") if a["type"] == "Queue reordered"]
    assert _blocks(api, creates) == 0


def test_going_ahead_anyway_flags_the_job_that_would_now_fail(api, login, add_uploaded, worker):
    login()
    creates, links = _pair(api, add_uploaded)
    assert api.post(f"/api/jobs/{links}/move", json={"toIndex": 0, "confirm": True}).status_code == 200
    checked = api.post(f"/api/jobs/{creates}/check").json()
    assert checked["counts"]["block"] == 1
    assert any("Job “Links or creates”, ahead of this one" in t for t in _checks(checked["rows"][0], "block"))
    assert _blocks(api, links) == 0
    # a flag, not a block: the job still runs, and the worker fails that document before creating anything for it
    assert worker.tick() and worker.tick()
    assert api.get(f"/api/jobs/{links}").json()["job"]["status"] == "Completed"
    ran = api.get(f"/api/jobs/{creates}").json()
    assert ran["job"]["status"] == "NeedsAttention"
    assert ran["rows"][0]["result"]["state"] == "Failed" and ran["rows"][0]["result"]["error"]["code"] == "object_exists"
    assert ran["created"]["media"] == 0


def test_run_now_and_hold_are_warned_about_too(api, login, add_uploaded):
    login()
    creates, links = _pair(api, add_uploaded)
    for path, body in ((f"/api/jobs/{links}/run-now", {"on": True}), (f"/api/jobs/{creates}/hold", {"on": True})):
        r = api.post(path, json=body)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "would_fail", (path, r.text)
        assert _blocks(api, creates) == 0
    # changes that make nothing fail go through without a question
    assert api.post(f"/api/jobs/{creates}/run-now", json={"on": True}).status_code == 200
    assert api.post(f"/api/jobs/{links}/hold", json={"on": True}).status_code == 200
    assert api.post(f"/api/jobs/{links}/hold", json={"on": False}).status_code == 200
    assert api.post(f"/api/jobs/{creates}/run-now", json={"on": False}).status_code == 200
    # confirmed
    assert api.post(f"/api/jobs/{links}/run-now", json={"on": True, "confirm": True}).status_code == 200
    assert _blocks(api, creates) == 1
    # undoing it makes nothing new fail, so it isn't asked about
    assert api.post(f"/api/jobs/{links}/run-now", json={"on": False}).status_code == 200
    assert _blocks(api, creates) == 0


def test_a_change_isnt_asked_about_again_for_a_failure_the_queue_already_has(api, login, add_uploaded):
    login()
    creates, links = _pair(api, add_uploaded)
    other, _ = _queued(api, add_uploaded, "Unrelated", "1-2345_x.jpg", "link")
    assert api.post(f"/api/jobs/{links}/move", json={"toIndex": 0, "confirm": True}).status_code == 200
    assert api.post(f"/api/jobs/{other}/move", json={"toIndex": 0}).status_code == 200  # the failure isn't new


# ---- Reorder to avoid failures -------------------------------------------------------------------------------------
def test_reorder_to_avoid_failures_moves_only_what_must_move(api, login, add_uploaded, services, worker):
    login()
    unrelated, _ = _queued(api, add_uploaded, "Unrelated", "1-2345_x.jpg", "link")
    creates, links = _pair(api, add_uploaded)
    last, _ = _queued(api, add_uploaded, "Last", "12-5678_1.jpg", "link")
    assert api.get("/api/queue/collisions").json() == {"problems": [], "order": [unrelated, creates, links, last], "moves": [],
                                                       "remaining": [], "changes": False}
    assert api.post("/api/queue/reorder-to-avoid-failures").status_code == 409  # nothing to do
    assert api.post(f"/api/jobs/{links}/move", json={"toIndex": 0, "confirm": True}).status_code == 200
    plan = api.get("/api/queue/collisions").json()
    assert [p["name"] for p in plan["problems"]] == ["Creates it"] and plan["changes"] is True
    assert plan["moves"] == ["“Creates it” ahead of “Links or creates”"] and plan["remaining"] == []
    assert plan["order"] == [unrelated, creates, links, last]  # the others keep their places

    done = api.post("/api/queue/reorder-to-avoid-failures")
    assert done.status_code == 200 and done.json()["problems"] == []
    queued = sorted((j for j in services.storage.list_jobs("pahma") if j["status"] == "Queued"), key=sched.queue_key)
    assert [j["id"] for j in queued] == [unrelated, creates, links, last]
    entry = [a for a in services.storage.list_audit("pahma") if a["type"] == "Queue reordered"][0]
    assert entry["detail"] == "Reordered the queue to avoid failures: moved “Creates it” ahead of “Links or creates”."
    for job in (creates, links):
        assert _blocks(api, job) == 0
    while worker.tick():
        pass
    assert {api.get(f"/api/jobs/{j}").json()["job"]["status"] for j in (creates, links, unrelated, last)} == {"Completed"}


def test_reorder_is_for_staff_and_everyone_sees_the_plan(api, login, add_uploaded, services):
    login()
    creates, links = _pair(api, add_uploaded)
    assert api.post(f"/api/jobs/{links}/move", json={"toIndex": 0, "confirm": True}).status_code == 200
    other = _second_user(services, "intern")
    assert other.get("/api/queue/collisions").json()["changes"] is True
    assert other.post("/api/queue/reorder-to-avoid-failures").status_code == 403


def test_reorder_says_when_a_setting_decides_the_order(api, login, add_uploaded, services):
    login()
    creates, links = _pair(api, add_uploaded)
    assert api.post(f"/api/jobs/{links}/run-now", json={"on": True, "confirm": True}).status_code == 200
    plan = api.get("/api/queue/collisions").json()
    assert len(plan["problems"]) == 1 and plan["changes"] is False and plan["moves"] == []
    assert plan["remaining"] == ["“20-0501.jpg” in “Creates it”: “Links or creates” would create object 20-0501 first "
                                 "(“Links or creates” has Run now, so it runs first whatever its place; undo Run now to change that)."]
    r = api.post("/api/queue/reorder-to-avoid-failures")
    assert r.status_code == 409 and r.json()["detail"] == "Reordering the queue wouldn't avoid any failure."
    assert services.storage.get_job(links)["runNow"] is True  # a scheduler's Run now is never undone for them
    # a hold on the job that has to go first
    assert api.post(f"/api/jobs/{links}/run-now", json={"on": False}).status_code == 200
    assert api.post(f"/api/jobs/{creates}/hold", json={"on": True, "confirm": True}).status_code == 200
    assert "“Creates it” is on hold" in api.get("/api/queue/collisions").json()["remaining"][0]


def test_reorder_says_when_no_order_works(api, login, add_uploaded, services):
    """Each job creates an object the other links or creates: each has to run before the other."""
    login()
    a = new_job(api, "Job A")
    rows = add_uploaded(a, ["77-1.jpg", "77-2.jpg"])
    api.patch(f"/api/jobs/{a}/rows/{rows[0]['n']}", json={"handling": "create"})
    api.patch(f"/api/jobs/{a}/rows/{rows[1]['n']}", json={"handling": "linkorcreate"})
    assert api.post(f"/api/jobs/{a}/schedule").status_code == 200
    b = new_job(api, "Job B")
    rows = add_uploaded(b, ["77-1_b.jpg", "77-2_b.jpg"])
    api.patch(f"/api/jobs/{b}/rows/{rows[0]['n']}", json={"handling": "linkorcreate"})
    api.patch(f"/api/jobs/{b}/rows/{rows[1]['n']}", json={"handling": "create"})
    blocked = api.post(f"/api/jobs/{b}/schedule")
    assert blocked.status_code == 409  # Submit refuses it: Job A would create 77-2 first
    # as two submissions at the same moment, each missing the other, would have queued them
    services.storage.update_job(b, {"status": "Queued", "queuedAt": services.clock(), "queuePos": services.clock(),
                                    "editingSession": None, "editingBy": None})
    services.queue_rows.clear()
    plan = api.get("/api/queue/collisions").json()
    assert [p["name"] for p in plan["problems"]] == ["Job B"] and plan["changes"] is False and plan["moves"] == []
    assert plan["remaining"] == ["“77-2_b.jpg” in “Job B”: “Job A” would create object 77-2 first "
                                 "(no order avoids it: edit one of the two jobs)."]
    assert api.post("/api/queue/reorder-to-avoid-failures").status_code == 409


HANDLINGS = ("link", "linkorcreate", "create", "mediaonly")


def test_every_pair_of_handlings_in_both_orders(api, login, add_uploaded, worker, services):
    """For an object number CollectionSpace doesn't have. Whatever Submit lets into the queue runs to the end in
    the order submitted. Reversed, either it still does, or the scheduler was warned, the job is flagged, and
    Reorder to avoid failures puts it right."""
    login()
    allowed, warned = [], []
    for i, first_handling in enumerate(HANDLINGS):
        for k, second_handling in enumerate(HANDLINGS):
            for swap in (False, True):
                num, pair = f"77-{i}{k}{int(swap)}", (first_handling, second_handling)
                one, _ = _job(api, add_uploaded, f"one {num}", f"{num}.jpg", first_handling)
                if api.post(f"/api/jobs/{one}/schedule").status_code != 200:
                    assert first_handling == "link"  # no such object to link to
                    api.delete(f"/api/jobs/{one}")
                    continue
                two, _ = _job(api, add_uploaded, f"two {num}", f"{num}_b.jpg", second_handling)
                if api.post(f"/api/jobs/{two}/schedule").status_code != 200:
                    api.delete(f"/api/jobs/{two}")
                    assert worker.tick()
                    services.queue_rows.clear()
                    continue
                allowed.append(pair)
                assert _blocks(api, one) == 0 and _blocks(api, two) == 0, pair
                if swap:
                    r = api.post(f"/api/jobs/{two}/move", json={"toIndex": 0})
                    if r.status_code == 409:
                        warned.append(pair)
                        assert api.post(f"/api/jobs/{two}/move", json={"toIndex": 0, "confirm": True}).status_code == 200
                        assert _blocks(api, one) == 1, pair
                        assert api.post("/api/queue/reorder-to-avoid-failures").status_code == 200
                    assert _blocks(api, one) == 0 and _blocks(api, two) == 0, pair
                assert worker.tick() and worker.tick()
                services.queue_rows.clear()
                for job in (one, two):
                    got = api.get(f"/api/jobs/{job}").json()
                    assert got["job"]["status"] == "Completed", (pair, swap, got["rows"][0]["result"])
    assert sorted(set(allowed)) == sorted({("linkorcreate", "linkorcreate"), ("linkorcreate", "mediaonly"), ("create", "linkorcreate"),
                                           ("create", "mediaonly"), ("mediaonly", "linkorcreate"), ("mediaonly", "create"),
                                           ("mediaonly", "mediaonly")})
    assert warned == [("create", "linkorcreate")]  # the one pair whose order matters


def test_ahead_of_follows_the_workers_order():
    s = sched.normalize({"days": [1, 2, 3, 4, 5, 6, 7], "start": "19:00", "end": "", "paused": None})
    q = lambda i, **kw: {"id": i, "status": "Queued", "queuePos": int(i[1:]), "queuedAt": 0, **kw}  # noqa: E731
    jobs = [{"id": "run", "status": "Running"}, q("q1"), q("q2", held={"by": "x"}), q("q3"), q("q4", runNow=True)]
    ids = lambda job: [j["id"] for j in sched.ahead_of(jobs, job, s, 1000.0, True)]  # noqa: E731
    assert ids({"id": "d", "status": "Draft"}) == ["run", "q1", "q2", "q3", "q4"]  # a draft joins the end
    assert ids(jobs[1]) == ["run", "q4"]             # Run now goes first
    assert ids(jobs[3]) == ["run", "q1", "q4"]       # the held job isn't ahead of it
    assert ids(jobs[2]) == ["run", "q1", "q3", "q4"]  # a held job runs after the others
    assert ids(jobs[4]) == ["run"]
    assert ids(jobs[0]) == []
