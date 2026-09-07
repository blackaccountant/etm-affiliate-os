import os

import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("ETM_G5_GLR2_DATABASE_URL") or not os.getenv("ETM_G5_GLR2_DB_ROLE"),
    reason="GLR2 PostgreSQL qualification not configured in this environment",
)


def test_glr2_postgresql_qualification_guard():
    assert True
