from app.memory.memory_bus import MemoryBus


def test_memory_bus_store_and_retrieve():

    memory = MemoryBus()

    memory.store(
        "company",
        "OpenRouter"
    )

    result = memory.get(
        "company"
    )

    assert result == "OpenRouter"


def test_memory_bus_exists():

    memory = MemoryBus()

    memory.store(
        "score",
        85
    )

    assert memory.exists("score") is True
    assert memory.exists("missing") is False


def test_memory_bus_delete():

    memory = MemoryBus()

    memory.store(
        "temp",
        "data"
    )

    memory.delete(
        "temp"
    )

    assert memory.get("temp") is None