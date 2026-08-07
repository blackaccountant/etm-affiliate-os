from app.system.runtime import RuntimeAdapter


def test_runtime_adapter_exists():

    runtime = RuntimeAdapter()

    assert runtime is not None


def test_memory_count():

    runtime = RuntimeAdapter()

    count = runtime.get_memory_count()

    assert isinstance(count, int)


def test_queue_status():

    runtime = RuntimeAdapter()

    status = runtime.get_queue_status()

    assert "pending" in status


def test_workers():

    runtime = RuntimeAdapter()

    workers = runtime.get_workers()

    assert isinstance(workers, list)