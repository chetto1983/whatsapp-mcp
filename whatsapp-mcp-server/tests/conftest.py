import pytest

from tenant_context import tenant_scope

TEST_IDENTITY = "11111111-1111-4111-8111-111111111111"
TEST_BRIDGE_TOKEN = "bridge-token-for-tests"


@pytest.fixture(autouse=True)
def tenant_context(tmp_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_STORE_ROOT", str(tmp_path / "whatsapp-root"))
    monkeypatch.setenv("WHATSAPP_BRIDGE_TOKEN", TEST_BRIDGE_TOKEN)
    with tenant_scope(TEST_IDENTITY):
        yield
