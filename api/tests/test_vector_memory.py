from __future__ import annotations

from app import vector_memory


def test_memory_is_persisted_scoped_and_recalled(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'memory.db'}")

    shared = vector_memory.add_memory(
        "tenant-a", "Northstar refunds are available within 30 days.",
        memory_type="business_rule", source="policy", metadata={"approved": True},
    )
    private = vector_memory.add_memory(
        "tenant-a", "User prefers order status updates first.",
        memory_type="preference", owner_id="user-1",
    )
    vector_memory.add_memory("tenant-b", "Northstar refunds are unavailable.")

    results = vector_memory.search_memories("tenant-a", "refund policy", owner_id="user-1", threshold=0.05)
    assert [item["id"] for item in results] == [shared["id"]]
    assert vector_memory.search_memories("tenant-a", "order updates", owner_id="user-1", threshold=0.05)[0]["id"] == private["id"]
    assert vector_memory.search_memories("tenant-b", "refund policy", threshold=0.05)[0]["content"] == "Northstar refunds are unavailable."


def test_memory_update_delete_forget_and_expiry(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'memory.db'}")

    item = vector_memory.add_memory("tenant-a", "Initial fact", owner_id="user-1", expires_in_days=1)
    assert vector_memory.update_memory(item["id"], "tenant-a", owner_id="user-2", content="blocked") is None
    updated = vector_memory.update_memory(item["id"], "tenant-a", owner_id="user-1", content="Updated fact", clear_expiry=True)
    assert updated and updated["content"] == "Updated fact" and updated["expires_at"] is None
    assert vector_memory.delete_memory(item["id"], "tenant-a", owner_id="user-2") is False
    assert vector_memory.delete_memory(item["id"], "tenant-a", owner_id="user-1") is True

    tenant_item = vector_memory.add_memory("tenant-a", "Shared fact")
    user_item = vector_memory.add_memory("tenant-a", "Private fact", owner_id="user-1")
    assert vector_memory.forget_memories("tenant-a", owner_id="user-1") == 1
    assert vector_memory.get_memory(user_item["id"], "tenant-a", owner_id="user-1") is None
    assert vector_memory.get_memory(tenant_item["id"], "tenant-a") is not None


def test_memory_context_labels_retrieved_data(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'memory.db'}")
    vector_memory.add_memory("tenant-a", "The renewal window is 14 days.", memory_type="business_rule")
    context = vector_memory.memory_context("tenant-a", "renewal window", threshold=0.05)
    assert "untrusted reference data" in context
    assert "14 days" in context
