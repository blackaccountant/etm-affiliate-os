"""
Generated Worker Test
"""


from app.ai.workers.s_e_o_hunter import SEOHunterWorker



def test_worker_creation():

    worker = SEOHunterWorker()

    assert (
        worker.name
        ==
        "SEOHunter"
    )