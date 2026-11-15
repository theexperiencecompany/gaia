from app.config.settings import Settings


def test_the_api_keeps_its_pool_sizes() -> None:
    api = Settings(WORKER_TYPE="main_app")

    assert api.mongo_max_pool_size == 20
    assert api.sqlalchemy_pool_size == 5
    assert api.sqlalchemy_max_overflow == 10


def test_the_arq_worker_gets_the_pools_its_concurrency_needs() -> None:
    worker = Settings(WORKER_TYPE="arq_worker")

    assert worker.mongo_max_pool_size == 50
    assert worker.sqlalchemy_pool_size == 10
    assert worker.sqlalchemy_max_overflow == 10
