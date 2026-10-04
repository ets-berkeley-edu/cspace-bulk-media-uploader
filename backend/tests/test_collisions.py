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


def test_two_jobs_that_create_the_same_object_the_second_must_be_fixed(api, login, add_uploaded, worker, services):
    login()
    first, _ = _job(api, add_uploaded, "First batch", f"{MISSING}.jpg", "create")
    assert api.post(f"/api/jobs/{first}/schedule").status_code == 200
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "create")
    blocks = _checks(_row(api, second, n), "block")
    assert len(blocks) == 1 and "Job “First batch”, ahead of this one in the job queue, creates object 20-0501" in blocks[0]
    assert "Submit this job after that one has run" in blocks[0] and f"({MISSING}.jpg)" in blocks[0]
    r = api.post(f"/api/jobs/{second}/schedule")
    assert r.status_code == 409 and r.json()["detail"]["rows"] == [n]
    # run the first job, then link to the object it created
    assert worker.tick()
    services.queue_rows.clear()  # the web app keeps the queue's documents for 5 seconds
    api.patch(f"/api/jobs/{second}/rows/{n}", json={"handling": "linkorcreate"})
    assert _checks(_row(api, second, n), "block") == []
    assert api.post(f"/api/jobs/{second}/schedule").status_code == 200
    assert worker.tick()
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
    blocks = _checks(_row(api, second, n), "block")
    # beside a "create if missing" document the fix is to do the same: two of those never collide
    assert len(blocks) == 1 and "creates object 20-0501" in blocks[0] and "choose “Link to object (create if missing)”" in blocks[0]


def test_link_or_create_behind_a_create_is_refused_so_no_queue_can_be_broken_by_reordering(api, login, add_uploaded, worker, services):
    login()
    first, _ = _job(api, add_uploaded, "First batch", f"{MISSING}.jpg", "create")
    assert api.post(f"/api/jobs/{first}/schedule").status_code == 200
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "linkorcreate")
    blocks = _checks(_row(api, second, n), "block")
    assert len(blocks) == 1 and "Job “First batch”, in the job queue, creates object 20-0501 with “Create new object + link”" in blocks[0]
    assert "can't wait in the queue together" in blocks[0]
    r = api.post(f"/api/jobs/{second}/schedule")
    assert r.status_code == 409 and r.json()["detail"]["rows"] == [n]
    # once the first job has run the object exists, and linking to it is fine
    assert worker.tick()
    services.queue_rows.clear()  # the web app keeps the queue's documents for 5 seconds
    assert _checks(_row(api, second, n), "block") == []
    assert api.post(f"/api/jobs/{second}/schedule").status_code == 200


def test_two_jobs_that_link_or_create_can_wait_together_in_either_order(api, login, add_uploaded, worker):
    login()
    first, _ = _job(api, add_uploaded, "First batch", f"{MISSING}.jpg", "linkorcreate")
    assert api.post(f"/api/jobs/{first}/schedule").status_code == 200
    second, n = _job(api, add_uploaded, "Second batch", f"{MISSING}_b.jpg", "linkorcreate")
    assert _checks(_row(api, second, n), "block") == []
    assert api.post(f"/api/jobs/{second}/schedule").status_code == 200
    assert api.post(f"/api/jobs/{second}/move", json={"toIndex": 0}).status_code == 200
    for job in (first, second):
        assert api.post(f"/api/jobs/{job}/check").json()["counts"]["block"] == 0
    assert worker.tick() and worker.tick()
    for job in (first, second):
        assert api.get(f"/api/jobs/{job}").json()["job"]["status"] == "Completed"


def test_the_same_identification_number_in_an_earlier_job_is_a_warning(api, login, add_uploaded):
    login()
    first, _ = _job(api, add_uploaded, "First batch", "1-2345_a.jpg", "link")
    assert api.post(f"/api/jobs/{first}/schedule").status_code == 200
    second, n = _job(api, add_uploaded, "Second batch", "1-2345_b.jpg", "link")
    warns = _checks(_row(api, second, n), "warn")
    assert any("Job “First batch”, ahead of this one in the job queue, also has a document with ID 1-2345" in t
               and "Both Media records would be created" in t for t in warns)
    assert api.post(f"/api/jobs/{second}/schedule").status_code == 200  # a warning doesn't stop Submit
    # the first job, which runs first, is told nothing
    one = api.post(f"/api/jobs/{first}/check").json()
    assert one["counts"] == {"block": 0, "warn": 0}


def test_a_queue_built_before_the_rule_shows_the_problem_on_the_job_that_runs_second(api, login, add_uploaded, services):
    """Two people submitting at the same moment can each miss the other. The Job queue then follows the real order."""
    login()  # admin is a BMU scheduler
    creates, _ = _job(api, add_uploaded, "Creates it", f"{MISSING}.jpg", "create")
    assert api.post(f"/api/jobs/{creates}/schedule").status_code == 200
    links, _ = _job(api, add_uploaded, "Links or creates", f"{MISSING}_b.jpg", "linkorcreate")
    # put it in the queue as a submission that missed the other job would have
    services.storage.update_job(links, {"status": "Queued", "queuedAt": services.clock(), "queuePos": services.clock(),
                                        "editingSession": None, "editingBy": None})
    services.queue_rows.clear()
    assert api.post(f"/api/jobs/{creates}/check").json()["counts"]["block"] == 0
    assert api.post(f"/api/jobs/{links}/check").json()["counts"]["block"] == 0  # in this order nothing fails
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


HANDLINGS = ("link", "linkorcreate", "create", "mediaonly")


def test_no_queue_that_submit_allows_can_be_broken_by_reordering(api, login, add_uploaded, worker, services):
    """Every pair of handlings, for an object number CollectionSpace doesn't have: whenever Submit lets both jobs
    into the queue, they run to the end in the order submitted and in the other order."""
    login()
    allowed = []
    for i, first_handling in enumerate(HANDLINGS):
        for j, second_handling in enumerate(HANDLINGS):
            for swap in (False, True):
                num = f"77-{i}{j}{int(swap)}"
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
                allowed.append((first_handling, second_handling))
                if swap:
                    assert api.post(f"/api/jobs/{two}/move", json={"toIndex": 0}).status_code == 200
                for job in (one, two):
                    assert api.post(f"/api/jobs/{job}/check").json()["counts"]["block"] == 0, (first_handling, second_handling, swap)
                assert worker.tick() and worker.tick()
                services.queue_rows.clear()
                for job in (one, two):
                    got = api.get(f"/api/jobs/{job}").json()
                    assert got["job"]["status"] == "Completed", (first_handling, second_handling, swap, got["rows"][0]["result"])
    # what may wait together: anything with a media-only job, and two jobs that both link or create
    assert sorted(set(allowed)) == sorted({("linkorcreate", "linkorcreate"), ("linkorcreate", "mediaonly"), ("create", "mediaonly"),
                                           ("mediaonly", "linkorcreate"), ("mediaonly", "create"), ("mediaonly", "mediaonly")})


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
