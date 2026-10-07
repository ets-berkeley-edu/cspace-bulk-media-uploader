"""Running several environments (local with the simulator, local against PAHMA QA, AWS): each one says which it
is, and two on one host keep separate sign-ins."""


def test_the_environment_label_and_whether_collectionspace_is_real_need_no_sign_in(api, services):
    from bmu.app import real_cspace
    assert api.get("/api/env").json() == {"label": "", "realCollectionSpace": False,  # tests use the simulator
                                          "tenants": [{"key": "pahma", "name": "PAHMA"}]}
    services.settings.env_label = "Local · PAHMA QA"
    assert api.get("/api/env").json()["label"] == "Local · PAHMA QA"
    assert real_cspace("https://pahma.qa.collectionspace.org") and not real_cspace("http://fakecspace:8180")


def test_the_simulator_in_aws_is_not_a_real_collectionspace(api, services):
    from bmu.app import real_cspace
    aws_simulator = "http://fakecspace.bmu-dev.internal:8180"  # SIMULATED_CSPACE=true (deploy/terraform/app/fakecspace.tf)
    assert real_cspace(aws_simulator) and not real_cspace(aws_simulator, simulated=True)
    services.settings.cspace_url = aws_simulator
    assert api.get("/api/env").json()["realCollectionSpace"] is True  # the host name alone can't tell
    services.settings.cspace_simulated = True
    assert api.get("/api/env").json()["realCollectionSpace"] is False


def test_the_session_cookie_name_is_a_setting(api, login, services):
    services.settings.cookie_name = "bmu_session_qa"  # two local environments on one host don't sign each other out
    login()
    assert "bmu_session_qa" in api.cookies and "bmu_session" not in api.cookies
    assert api.get("/api/me").status_code == 200
    api.post("/api/logout")
    assert api.get("/api/me").status_code == 401
