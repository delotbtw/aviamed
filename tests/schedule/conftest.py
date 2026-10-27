import pytest_asyncio

from tests.schedule.support import assert_schedule_invariants


@pytest_asyncio.fixture(autouse=True)
async def _schedule_invariants(request, sql):
    """Spec 6: every stage 2 test ends with assert_schedule_invariants (opt out: @pytest.mark.no_schedule_invariants).

    Teardown runs before `sql` / `clean_db` truncate the data.
    """
    yield
    if not request.node.get_closest_marker("no_schedule_invariants"):
        await assert_schedule_invariants(sql)
