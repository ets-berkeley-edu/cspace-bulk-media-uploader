"""Groups (design: Groups; The Group step): one new Group per job, each Object added once, reruns reuse it."""


def new_job(api, name="Survey batch 4"):
    return api.post("/api/jobs", json={"name": name}).json()["id"]


def test_the_group_title_starts_empty_and_never_follows_the_job_name(api, login, add_uploaded):
    """User decision (design: Groups): turning the group on leaves the title empty and required; the editor's
    "Use the job name" and "Use a timestamp" fill it once, and renaming the job never changes it."""
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    j = api.patch(f"/api/jobs/{job}", json={"groupOn": True}).json()
    assert j["groupOn"] and not j.get("groupTitle")
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 409 and "Enter a group title" in r.json()["detail"]
    j = api.patch(f"/api/jobs/{job}", json={"groupTitle": "Survey batch 4"}).json()  # "Use the job name"
    assert j["groupTitle"] == "Survey batch 4"
    j = api.patch(f"/api/jobs/{job}", json={"name": "Survey batch 5"}).json()
    assert j["name"] == "Survey batch 5" and j["groupTitle"] == "Survey batch 4"
    # turning the group off and on again keeps the title
    api.patch(f"/api/jobs/{job}", json={"groupOn": False})
    j = api.patch(f"/api/jobs/{job}", json={"groupOn": True}).json()
    assert j["groupTitle"] == "Survey batch 4"


def test_a_job_saved_with_a_title_following_its_name_keeps_it(api, login, services):
    """Jobs from before the change keep their title; the old follow-the-name flag is ignored."""
    login()
    job = new_job(api)
    services.storage.update_job(job, {"groupOn": True, "groupTitle": "bmu-survey-batch-4", "groupTitleAuto": True})
    j = api.patch(f"/api/jobs/{job}", json={"name": "Survey batch 5"}).json()
    assert j["groupTitle"] == "bmu-survey-batch-4"


def test_a_group_title_is_required(api, login, add_uploaded):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    api.patch(f"/api/jobs/{job}", json={"groupOn": True, "groupTitle": ""})
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 409 and "Enter a group title" in r.json()["detail"]


def test_the_group_is_created_once_and_each_object_joins_once(api, login, add_uploaded, worker, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "15-1234_2.jpg", "12-5678_1.jpg", "3-1001.jpg", "1-2345.jpg"])
    api.patch(f"/api/jobs/{job}", json={"groupOn": True, "groupTitle": "Survey batch 4"})
    api.patch(f"/api/jobs/{job}/rows/4", json={"group": False})  # left out
    api.patch(f"/api/jobs/{job}/rows/5", json={"handling": "mediaonly"})  # no object: can't join
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "Completed", j["job"]
    assert len(fake.groups) == 1 and list(fake.groups.values())[0]["title"] == "Survey batch 4"
    group = j["job"]["groupStep"]["csid"]
    steps = {r["file"]: r["result"]["steps"] for r in j["rows"]}
    assert steps["15-1234_1.jpg"]["addToGroup"]["csid2"]
    assert steps["15-1234_2.jpg"]["addToGroup"]["sameAs"] == 1  # the same Object, added once
    assert "addToGroup" not in steps["3-1001.jpg"] and "addToGroup" not in steps["1-2345.jpg"]
    group_rels = [r for r in fake.relations.values() if group in (r["subjectCsid"], r["objectCsid"])]
    assert len(group_rels) == 4  # two Objects, both directions
    assert {r["subjectDocumentType"] for r in group_rels} == {"Group", "CollectionObject"}
    assert j["created"]["groups"] == 1 and j["created"]["relations"] == 5 * 2 - 2 + 4


def test_group_failure_needs_attention_and_the_rerun_creates_it(api, login, add_uploaded, worker, fake, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg"])
    api.patch(f"/api/jobs/{job}", json={"groupOn": True, "groupTitle": "Survey batch 4"})
    fail_on("group", status=400)
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "NeedsAttention" and j["job"]["code"] == "group_failed"
    assert j["job"]["codeDetail"] == "Creating the group: POST groups returned 400"
    for r in j["rows"]:
        assert r["result"]["state"] == "Partial"
        assert r["result"]["steps"]["addToGroup"] == {"s": "skipped", "after": "group"}
        assert r["result"]["error"]["code"] == "group_failed"
        assert r["result"]["steps"]["upload"]["s"] == "done"  # the other steps still ran
    # fix: change the title and reschedule; only the group steps run again
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200
    assert api.patch(f"/api/jobs/{job}", json={"groupTitle": "fixed title"}).status_code == 200
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "Completed" and len(fake.groups) == 1
    assert list(fake.groups.values())[0]["title"] == "fixed title"
    assert len(fake.media) == 3  # 1 seeded + 2, nothing recreated


def test_turning_the_group_off_while_fixing_skips_the_group_steps(api, login, add_uploaded, worker, fake, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    api.patch(f"/api/jobs/{job}", json={"groupOn": True, "groupTitle": "Survey batch 4"})
    fail_on("group", status=500)
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    api.post(f"/api/jobs/{job}/fix")
    assert api.patch(f"/api/jobs/{job}", json={"groupOn": False}).status_code == 200
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "Completed"
    assert j["rows"][0]["result"]["steps"]["addToGroup"]["s"] == "not needed"
    assert not fake.groups


def test_a_user_who_cannot_create_groups_is_told_before_scheduling(api, login, add_uploaded):
    me = login("limited")
    assert me["perms"]["groups"] is False
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    r = api.patch(f"/api/jobs/{job}", json={"groupOn": True, "groupTitle": "Survey batch 4"}).json()
    row = r["rows"][0]
    assert any("can't create groups" in c["text"] for c in row["checks"])
    ok = api.patch(f"/api/jobs/{job}/rows/1", json={"group": False}).json()["row"]
    assert not any("can't create groups" in c["text"] for c in ok["checks"])


def test_the_group_cannot_change_once_it_exists(api, login, add_uploaded, worker, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    api.patch(f"/api/jobs/{job}", json={"groupOn": True, "groupTitle": "Survey batch 4"})
    fail_on("upload", status=413)
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    api.post(f"/api/jobs/{job}/fix")
    r = api.patch(f"/api/jobs/{job}", json={"groupTitle": "renamed"})
    assert r.status_code == 409 and "already exists" in r.json()["detail"]
    assert api.patch(f"/api/jobs/{job}/rows/1", json={"group": False}).status_code == 422  # its object is already in it
