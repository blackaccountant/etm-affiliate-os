"""
Generated Worker Test
"""


from app.ai.workers.content_writer import ContentWriterWorker



def test_worker_creation():

    worker = ContentWriterWorker()

    assert (
        worker.name
        ==
        "ContentWriter"
    )