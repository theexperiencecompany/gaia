"""Motor binds its client to the loop that built it, and pytest builds a new loop per test.

app.db.mongodb.collections caches that client in module globals for the life of the
process, so the second test to touch Mongo reused a client whose loop was already
closed and died with "Event loop is closed" — whichever test happened to run second.
Two tests in order are enough to make that deterministic.
"""

from app.db.mongodb.collections import get_async_collection


class TestMongoClientFollowsTheLoop:
    async def test_the_first_test_opens_the_shared_client(self) -> None:
        await get_async_collection("loop_probe").find_one({})

    async def test_the_second_test_reaches_mongo_on_its_own_loop(self) -> None:
        await get_async_collection("loop_probe").find_one({})
