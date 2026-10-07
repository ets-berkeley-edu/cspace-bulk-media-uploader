"""Serving the built Vue app (BMU_STATIC_DIR, as in the AWS image): the app's own files, the app for any other page,
nothing outside the build, and long caching only for the hashed files under /assets/."""
import pytest
from fastapi.testclient import TestClient

from bmu.app import create_app


@pytest.fixture
def site(services, tmp_path):
    build = tmp_path / "static"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text("<!doctype html><title>BMU</title>")
    (build / "assets" / "index-abc123.js").write_text("console.log('app')")
    (build / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("not for the browser")
    services.settings.static_dir = str(build)
    c = TestClient(create_app(services), base_url="http://testserver")
    c.headers["X-BMU"] = "1"
    return c


def test_the_app_and_its_files_are_served(site):
    assert "<title>BMU</title>" in site.get("/").text
    assert site.get("/favicon.svg").text == "<svg/>"
    assert "<title>BMU</title>" in site.get("/drafts/some-page").text  # the browser routes it
    js = site.get("/assets/index-abc123.js")
    assert js.status_code == 200 and js.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert site.get("/").headers["cache-control"] == "no-store"  # the app itself is never kept: a deploy shows at once
    assert site.get("/assets/missing.js").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/..%2fsecret.txt", "/%2e%2e%2fsecret.txt", "/..%2f..%2fetc/hostname",
                                  "/%2fetc/hostname", "/%2fproc/self/environ", "/assets/..%2f..%2fsecret.txt"])
def test_nothing_outside_the_build_is_served(site, path):
    r = site.get(path)
    assert "not for the browser" not in r.text and "PATH=" not in r.text
    assert r.status_code == 404 or "<title>BMU</title>" in r.text


def test_unknown_api_paths_are_404_not_the_app(site):
    assert site.get("/api/no-such-thing").status_code == 404
    assert site.get("/api").status_code == 404
    assert site.get("/api/health").json() == {"ok": True}


@pytest.mark.parametrize("path", ["/a%00b", "/%00", "/" + "a" * 300])
def test_odd_paths_get_the_app_not_an_error(site, path):
    r = site.get(path)  # a null byte or an over-long name used to be a 500
    assert r.status_code == 200 and "<title>BMU</title>" in r.text
