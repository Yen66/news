from src.db.repository import InMemoryRepository, build_repository, PostgresRepository
from src.models import Post
from tests.conftest import make_item


async def test_in_memory_roundtrip():
    repo = InMemoryRepository()
    await repo.connect()
    item = make_item("News", guid="g1")
    await repo.mark_sent(item)
    uids, keys = await repo.load_seen()
    assert item.uid in uids
    assert item.dedup_key in keys


async def test_archive_stores_post():
    repo = InMemoryRepository()
    item = make_item("News", guid="g2")
    post = Post(item=item, body="text", official=False, provider_used="groq")
    await repo.archive_post(post)
    assert repo.archived[0].body == "text"


def test_build_repository_selects_backend():
    assert isinstance(build_repository(""), InMemoryRepository)
    assert isinstance(
        build_repository("postgresql://u:p@h/db"), PostgresRepository
    )
