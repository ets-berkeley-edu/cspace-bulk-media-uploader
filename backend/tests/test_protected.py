"""Protected files (design: Protected files): set automatically from the linked Object's sensitivity."""
import pytest
from bmu.sensitivity import evaluate
from bmu.storage import now
from bmu.tenant import load_tenant


def new_job(api, name="Protected test"):
    return api.post("/api/jobs", json={"name": name}).json()["id"]


def by_file(rows):
    return {r["file"]: r for r in rows}


def test_rules_read_the_object_record():
    cfg = load_tenant("pahma").sensitivity
    xml = (b'<document><a:collectionobjects_common xmlns:a="x"><responsibleDepartments><responsibleDepartment>Human Remains'
           b'</responsibleDepartment></responsibleDepartments></a:collectionobjects_common><b:collectionobjects_pahma xmlns:b="y">'
           b'<pahmaObjectStatusList><pahmaObjectStatus>culturally sensitive</pahmaObjectStatus></pahmaObjectStatusList>'
           b'<accessRestrictionGroupList><accessRestrictionGroup><accessRestrictionType>publication</accessRestrictionType>'
           b'<accessRestrictionLevel>preference</accessRestrictionLevel></accessRestrictionGroup></accessRestrictionGroupList>'
           b'</b:collectionobjects_pahma></document>')
    out = evaluate(cfg, xml)
    assert out["hides"] and out["protect"] == ["culturally sensitive object in the Human Remains department"]
    assert out["warn"] == []  # a soft signal doesn't matter once protected
    # type and level must match within the same restriction entry
    mixed = (b'<d><accessRestrictionGroup><accessRestrictionType>display/visual</accessRestrictionType><accessRestrictionLevel>preference'
             b'</accessRestrictionLevel></accessRestrictionGroup><accessRestrictionGroup><accessRestrictionType>loan</accessRestrictionType>'
             b'<accessRestrictionLevel>restriction</accessRestrictionLevel></accessRestrictionGroup></d>')
    out = evaluate(cfg, mixed)
    assert out["protect"] == [] and out["warn"]


def test_documents_linked_to_sensitive_objects_are_protected(api, login, add_uploaded):
    login()
    job = new_job(api)
    add_uploaded(job, ["12-2001.jpg", "12-2002_a.jpg", "12-2003.jpg", "15-1234_1.jpg"])
    rows = by_file(api.post(f"/api/jobs/{job}/check").json()["rows"])
    hr, nagpra, soft, plain = rows["12-2001.jpg"], rows["12-2002_a.jpg"], rows["12-2003.jpg"], rows["15-1234_1.jpg"]
    assert hr["protected"]["hides"] and "Human Remains" in hr["protected"]["reason"]
    assert "NAGPRA" in nagpra["protected"]["reason"] and "display or publication restriction" in nagpra["protected"]["reason"]
    assert not nagpra["protected"]["hides"]
    # protected files default to Restricted; the others keep the tenant's default
    assert hr["restricted"] and nagpra["restricted"] and not soft["restricted"] and not plain["restricted"]
    assert any(c["level"] == "info" and c["text"].startswith("Protected file:") for c in hr["checks"])
    assert soft["protected"] is None and any(c["level"] == "warn" and "preference or recommendation" in c["text"] for c in soft["checks"])
    assert plain["protected"] is None
    # once the image is withheld, the soft signal stays visible as information, not a warning
    soft = api.patch(f"/api/jobs/{job}/rows/{soft['n']}", json={"restricted": True}).json()["row"]
    assert not any(c["level"] == "warn" for c in soft["checks"])
    assert any(c["level"] == "info" and "preference or recommendation" in c["text"] and "withheld" in c["text"] for c in soft["checks"])
    # users can't set or clear the flag
    assert api.patch(f"/api/jobs/{job}/rows/{plain['n']}", json={"protected": {"reason": "x"}}).status_code == 422
    # a protected draft expires after 7 days instead of 30
    j = api.get(f"/api/jobs/{job}").json()["job"]
    assert j["protectedCount"] == 2 and j["expiresAt"] < now() + 8 * 86400


def test_making_a_protected_file_public_warns_and_the_choice_stands(api, login, add_uploaded):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["12-2002.jpg"])[0]["n"]
    api.post(f"/api/jobs/{job}/check")
    r = api.patch(f"/api/jobs/{job}/rows/{n}", json={"restricted": False}).json()["row"]
    assert not r["restricted"] and r["protected"]
    assert any(c["level"] == "warn" and "would appear on the public portal" in c["text"] for c in r["checks"])
    r = api.post(f"/api/jobs/{job}/check", json={"rows": [n]}).json()["rows"][0]
    assert not r["restricted"]  # the automatic default doesn't override the user's choice


def test_changing_the_object_clears_the_flag_and_its_default(api, login, add_uploaded):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["12-2001.jpg"])[0]["n"]
    assert api.post(f"/api/jobs/{job}/check").json()["rows"][0]["restricted"]
    r = api.patch(f"/api/jobs/{job}/rows/{n}", json={"obj": "12-5678"}).json()["row"]
    assert r["protected"] is None and not r["restricted"]
    assert api.get(f"/api/jobs/{job}").json()["job"]["protectedCount"] == 0
    r = api.patch(f"/api/jobs/{job}/rows/{n}", json={"handling": "mediaonly"}).json()["row"]
    assert r["protected"] is None


def test_restricted_reaches_collectionspace(api, login, add_uploaded, worker, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["12-2001.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    row = api.get(f"/api/jobs/{job}").json()["rows"][0]
    assert "<approvedForWeb>false</approvedForWeb>" in fake.media[row["result"]["steps"]["media"]["csid"]]["xml"]


def test_protected_uploads_are_removed_from_stopped_jobs_after_7_days(api, login, add_uploaded, worker, services, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["12-2001.jpg", "15-1234_1.jpg"])
    fail_on("media", status=401)  # the job stops before either document is uploaded
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    assert worker.sweep_protected_staged() == []  # not yet
    services.storage.update_job(job, {"finishedAt": now() - 8 * 86400})
    removed = worker.sweep_protected_staged()
    rows = by_file(api.get(f"/api/jobs/{job}").json()["rows"])
    assert removed == [(job, rows["12-2001.jpg"]["n"])]
    assert rows["12-2001.jpg"]["upload"] == {"s": "failed", "reason": "removed"}
    assert services.storage.head_object(rows["12-2001.jpg"]["s3Key"]) is None
    assert rows["15-1234_1.jpg"]["upload"]["s"] == "done"
    # fixing: the document asks for its file again, and Retry takes it
    api.post(f"/api/jobs/{job}/fix")
    r = api.post(f"/api/jobs/{job}/check").json()["rows"]
    assert any("removed this protected file" in c["text"] for c in by_file(r)["12-2001.jpg"]["checks"])
    ok = api.post(f"/api/jobs/{job}/rows/{rows['12-2001.jpg']['n']}/retry-upload", json={"name": "12-2001.jpg", "size": 3, "type": "image/jpeg"})
    assert ok.status_code == 200


def test_a_draft_with_protected_files_expires_after_7_days_even_if_they_are_excluded_or_its_sign_in_expired(
        api, login, add_uploaded, worker, services):
    """Design (Drafts, Expiry): 7 days if any of its documents is a protected file."""
    login()
    job = new_job(api)
    add_uploaded(job, ["12-2001_1.jpg", "15-1234_1.jpg"])
    api.post(f"/api/jobs/{job}/check")
    j = services.storage.get_job(job)
    assert j["protectedCount"] == 1 and j["expiresAt"] - j["lastSavedAt"] == pytest.approx(7 * 86400, abs=5)
    api.patch(f"/api/jobs/{job}/rows/1", json={"include": False})  # excluded: the BMU still holds the file
    api.post(f"/api/jobs/{job}/check")
    assert services.storage.get_job(job)["protectedCount"] == 1
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    services.storage.update_job(job, {"credentialExpires": 1})
    assert worker.sweep_expired_sign_ins() == [job]
    j = services.storage.get_job(job)
    assert j["status"] == "Draft" and j["expiresAt"] - now() == pytest.approx(7 * 86400, abs=5)


def test_a_running_job_past_the_sign_in_limit_loses_its_stored_sign_in(api, login, add_uploaded, worker, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    services.storage.update_job(job, {"status": "Running", "credentialExpires": 1})
    assert services.storage.get_credential(job)
    worker.sweep_expired_sign_ins()
    assert services.storage.get_credential(job) is None and services.storage.get_job(job)["status"] == "Running"
