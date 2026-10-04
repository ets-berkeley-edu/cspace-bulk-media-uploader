"""Jobs that collide in the queue (design: Jobs that collide in the queue): a job that runs first can change
CollectionSpace so that a later job's document fails. The checks compare a job with the jobs ahead of it."""
from bmu import schedule as sched
from test_flow import _checks, new_job

MISSING = "20-0501"  # an object number the simulated CollectionSpace doesn't have


def _job(api, add_uploaded, name, file, handling):
    job = new_job(api, name)
    row = add_uploaded(job, [file])[0]
    r = api.patch(f"/api/jobs/{job}/rows/{row['n']}", json={"handling": handling})
    assert r.status_code == 200, r.text
    return job, row["n"]


def _row(api, job, n):
    return next(r for r in api.post(f"/api/jobs/{job}/check").json()["rows"] if r["n"] == n)


def test_two_jobs_that_create_the_same_object_the_second_must_be_fixed(api, login, add_uploaded, worker):
    login()
    first, _ = _job(api, add_uploaded, "First batch", f"{MISSING}.jpg", "create")
    assert api.post(f"/api/jobs/{first}/schedule").status_code == 200
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
    first, _ = _job(api, add_uploaded, "First batch", f"{MISSING}.jpg", "linkorcreate")
    assert api.post(f"/api/jobs/{first}/schedule").status_code == 200
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "create")
    assert any("creates object 20-0501" in t for t in _checks(_row(api, second, n), "block"))


def test_a_job_that_links_or_creates_never_collides(api, login, add_uploaded):
    login()
    first, _ = _job(api, add_uploaded, "First batch", f"{MISSING}.jpg", "create")
    assert api.post(f"/api/jobs/{first}/schedule").status_code == 200
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "linkorcreate")
    assert _checks(_row(api, second, n), "block") == []
    assert api.post(f"/api/jobs/{second}/schedule").status_code == 200


def test_the_same_identification_number_in_an_earlier_job_is_a_warning(api, login, add_uploaded):
    login()
    first, _ = _job(api, add_uploaded, "First batch", f"{MISSING}.jpg", "create")
    assert api.post(f"/api/jobs/{first}/schedule").status_code == 200
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "linkorcreate")
    warns = _checks(_row(api, second, n), "warn")
    assert any("Job “First batch”, ahead of this one in the job queue, also has a document with ID 20-0501" in t
               and "Both Media records would be created" in t for t in warns)
    assert api.post(f"/api/jobs/{second}/schedule").status_code == 200  # a warning doesn't stop Submit
    # the first job, which runs first, is told nothing
    one = api.post(f"/api/jobs/{first}/check").json()
    assert one["counts"] == {"block": 0, "warn": 0}


def test_reordering_the_queue_moves_the_problem_to_the_job_that_now_runs_second(api, login, add_uploaded):
    login()  # admin is a BMU scheduler
    creates, n = _job(api, add_uploaded, "Creates it", f"{MISSING}.jpg", "create")
    assert api.post(f"/api/jobs/{creates}/schedule").status_code == 200
    links, _ = _job(api, add_uploaded, "Links or creates", f"{MISSING}_b.jpg", "linkorcreate")
    assert api.post(f"/api/jobs/{links}/schedule").status_code == 200
    assert api.post(f"/api/jobs/{creates}/check").json()["counts"]["block"] == 0
    # a scheduler puts the second job first: now it creates the object, and the first job's document would fail
    assert api.post(f"/api/jobs/{links}/move", json={"toIndex": 0}).status_code == 200
    checked = api.post(f"/api/jobs/{creates}/check").json()
    assert checked["counts"]["block"] == 1
    assert any("Job “Links or creates”, ahead of this one" in t for t in _checks(checked["rows"][0], "block"))
    # Run now does the same as moving
    assert api.post(f"/api/jobs/{links}/move", json={"toIndex": 1}).status_code == 200
    assert api.post(f"/api/jobs/{creates}/check").json()["counts"]["block"] == 0
    assert api.post(f"/api/jobs/{links}/run-now", json={"on": True}).status_code == 200
    assert api.post(f"/api/jobs/{creates}/check").json()["counts"]["block"] == 1


def test_once_the_first_job_has_run_collectionspace_itself_says_the_object_exists(api, login, add_uploaded, worker):
    login()
    first, _ = _job(api, add_uploaded, "First batch", f"{MISSING}.jpg", "create")
    assert api.post(f"/api/jobs/{first}/schedule").status_code == 200
    assert worker.tick()
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "create")
    blocks = _checks(_row(api, second, n), "block")
    assert len(blocks) == 1 and "already exists in CollectionSpace" in blocks[0] and "First batch" not in blocks[0]


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
