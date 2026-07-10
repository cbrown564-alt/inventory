from homeinventory.describe import TieredBackend, _hard_item
from homeinventory.schema import Item


class FakeBackend:
    model = "fake"

    def __init__(self, items):
        self.items = items
        self.calls = 0
        self.system_prompt = "base"

    def describe_room(self, *args):
        self.calls += 1
        return "summary", self.items


def item(name, *, confidence=0.9, defects=None, condition="good",
         cleanliness="cleaned to domestic standard"):
    return Item(id="", name=name, confidence=confidence,
                defects=defects or [], condition=condition,
                cleanliness=cleanliness)


def test_hard_item_router_covers_uncertainty_defects_and_missing_grades():
    assert not _hard_item(item("Table"))
    assert _hard_item(item("Table", confidence=0.4))
    assert _hard_item(item("Table", defects=["scratch"]))
    assert _hard_item(item("Table", condition=None))


def test_tiered_backend_calls_expert_only_for_hard_tail():
    easy = item("Table")
    hard = item("Oven", confidence=0.5)
    corrected = item("Oven", confidence=0.98, condition="fair")
    draft = FakeBackend([easy, hard])
    expert = FakeBackend([corrected, item("Invented", confidence=0.9)])
    backend = TieredBackend(draft, expert)
    _, result = backend.describe_room("Kitchen", [], [], {})
    assert draft.calls == expert.calls == 1
    assert [i.name for i in result] == ["Table", "Oven"]
    assert result[1].condition == "fair"
    assert backend.last_room_timing["corrected_items"] == 1


def test_tiered_backend_skips_expert_when_all_items_are_easy():
    draft = FakeBackend([item("Table")])
    expert = FakeBackend([])
    backend = TieredBackend(draft, expert)
    backend.describe_room("Kitchen", [], [], {})
    assert draft.calls == 1 and expert.calls == 0
