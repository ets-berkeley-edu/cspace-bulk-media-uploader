"""Section 5 of the 29 October 2026 review, in the app: https-only CollectionSpace servers, add-only audit entries."""
import pytest

from bmu.config import Settings


def _settings(**kw):
    return Settings(_env_file=None, session_key_b64="", job_key_b64="", **kw)


@pytest.mark.parametrize("url", ["http://pahma.qa.collectionspace.org", "ftp://pahma.qa.collectionspace.org"])
def test_a_real_collectionspace_server_must_be_https(url):
    with pytest.raises(ValueError, match="must be an https:// address"):
        _settings(tenants={"pahma": url}).museums()


@pytest.mark.parametrize("url, simulated", [("https://pahma.qa.collectionspace.org", False), ("http://fakecspace:8180", False),
                                            ("http://localhost:8180", False), ("http://fakecspace.bmu-dev.internal:8180", True)])
def test_https_servers_and_the_simulator_are_accepted(url, simulated):
    assert _settings(tenants={"pahma": url}, cspace_simulated=simulated).museums() == {"pahma": url}


def test_an_audit_entry_is_never_replaced(services):
    s = services.storage
    s.audit("pahma", "Test", "admin", "j1", "first")
    entry = s.list_audit("pahma")[0]
    item = {**entry, "detail": "rewritten"}
    with pytest.raises(Exception, match="ConditionalCheckFailed"):
        s.audit_table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    s.index_csid("pahma", "c1", job="j1")
    s.index_csid("pahma", "c1", job="j2")  # a second entry for the same CSID doesn't replace the first
    assert s.find_csid("c1")["job"] == "j1"
