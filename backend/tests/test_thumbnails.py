"""Thumbnails (design: User interface, Thumbnails)."""
import io

from PIL import Image

from bmu.thumbnails import make_thumbnail


def jpeg_with_exif(size=(800, 600)) -> bytes:
    im = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "Camera maker"  # Make
    out = io.BytesIO()
    im.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


def tiff(size=(1200, 900)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (10, 90, 200)).save(out, "TIFF")
    return out.getvalue()


def new_job(api):
    return api.post("/api/jobs", json={"name": "Thumbs"}).json()["id"]


def test_thumbnails_are_small_and_carry_no_metadata():
    t = make_thumbnail(jpeg_with_exif())
    with Image.open(io.BytesIO(t)) as im:
        assert max(im.size) == 320 and im.format == "JPEG"
        assert not im.getexif() and "icc_profile" not in im.info


def test_browser_thumbnails_are_stored_rewritten_and_served(api, login, add_uploaded):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    assert api.get(f"/api/jobs/{job}/rows/{n}/thumbnail").status_code == 404
    r = api.post(f"/api/jobs/{job}/rows/{n}/thumbnail", content=jpeg_with_exif((300, 200)), headers={"Content-Type": "image/jpeg"})
    assert r.json() == {"stored": True}
    got = api.get(f"/api/jobs/{job}/rows/{n}/thumbnail")
    assert got.status_code == 200 and got.headers["cache-control"] == "private, max-age=300"
    with Image.open(io.BytesIO(got.content)) as im:
        assert not im.getexif()  # rewritten on the server: nothing but pixels
    assert api.post(f"/api/jobs/{job}/rows/{n}/thumbnail", content=b"not an image").status_code == 422
    assert api.post(f"/api/jobs/{job}/rows/{n}/thumbnail", content=b"x" * 400_000).status_code == 413


def test_tiff_thumbnails_are_made_on_the_server(api, login, services):
    login()
    job = new_job(api)
    data = tiff()
    row = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": "15-1234_2.tif", "size": len(data), "type": "image/tiff"}]}).json()["rows"][0]
    services.storage.s3.put_object(Bucket=services.settings.s3_bucket, Key=row["s3Key"], Body=data)
    api.post(f"/api/jobs/{job}/rows/{row['n']}/uploaded")  # the thumbnail step runs after the response
    got = api.get(f"/api/jobs/{job}/rows/{row['n']}/thumbnail")
    assert got.status_code == 200
    with Image.open(io.BytesIO(got.content)) as im:
        assert im.size == (320, 240)


def test_no_thumbnail_is_kept_for_a_protected_file(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["12-2001.jpg"])[0]["n"]
    assert services.storage.store_thumbnail("pahma", job, n, make_thumbnail(jpeg_with_exif((100, 100)))) is False  # already protected
    # stored before the checks found the object sensitive...
    key = f"staging/pahma/{job}/{n:05d}/thumb-early"
    services.storage.put_bytes(key, b"jpeg", "image/jpeg")
    row = services.storage.get_row(job, n)
    row.update(thumbKey=key, protected=None)
    services.storage.put_row(job, row)
    api.post(f"/api/jobs/{job}/check", json={"rows": [n]})
    # ...and deleted at once when they did
    assert services.storage.get_row(job, n)["thumbKey"] is None and services.storage.head_object(key) is None
    assert api.get(f"/api/jobs/{job}/rows/{n}/thumbnail").status_code == 404
    assert api.post(f"/api/jobs/{job}/rows/{n}/thumbnail", content=jpeg_with_exif((50, 50))).json() == {"stored": False}


def test_after_the_upload_the_thumbnail_comes_from_collectionspace(api, login, services, worker, fake):
    login()
    job = new_job(api)
    data = jpeg_with_exif((64, 48))
    row = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": "15-1234_3.jpg", "size": len(data), "type": "image/jpeg"}]}).json()["rows"][0]
    services.storage.s3.put_object(Bucket=services.settings.s3_bucket, Key=row["s3Key"], Body=data)
    api.post(f"/api/jobs/{job}/rows/{row['n']}/uploaded")
    api.post(f"/api/jobs/{job}/rows/{row['n']}/thumbnail", content=make_thumbnail(data))
    key = services.storage.get_row(job, row["n"])["thumbKey"]
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    after = services.storage.get_row(job, row["n"])
    assert after["thumbKey"] is None and services.storage.head_object(key) is None  # deleted with the staged file
    got = api.get(f"/api/jobs/{job}/rows/{row['n']}/thumbnail?size=large")
    assert got.status_code == 200 and got.content == data  # the simulator serves the file as its derivative


def test_deleting_a_document_deletes_its_thumbnail(api, login, add_uploaded, services):
    """Design (Deleting a row): the row item, its staged file and its thumbnail."""
    login()
    job = api.post("/api/jobs", json={"name": "t"}).json()["id"]
    row = add_uploaded(job, ["15-1234_a.jpg"])[0]
    assert services.storage.store_thumbnail("pahma", job, row["n"], make_thumbnail(jpeg_with_exif((100, 100))))
    got = services.storage.get_row(job, row["n"])
    thumb, staged = got["thumbKey"], got["s3Key"]
    assert services.storage.head_object(thumb) and services.storage.head_object(staged)
    assert api.delete(f"/api/jobs/{job}/rows/{row['n']}").status_code == 200
    assert services.storage.head_object(thumb) is None and services.storage.head_object(staged) is None
