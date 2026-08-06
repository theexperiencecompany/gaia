"""Contract tests for IntegrationsRepository (global, keyed by integration_id)."""

from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest

from app.db.repositories.integrations import IntegrationsRepository
from app.models.integration_models import Integration, IntegrationTool
from app.models.mcp_config import MCPConfig


@pytest.fixture
def repo(raw_collection) -> IntegrationsRepository:
    return IntegrationsRepository()


def _integration(integration_id: str, name: str, **overrides: object) -> Integration:
    data: dict[str, object] = {
        "integration_id": integration_id,
        "name": name,
        "description": "desc",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
        "mcp_config": MCPConfig(server_url="https://mcp.example.com", requires_auth=False),
    }
    data.update(overrides)
    return Integration.model_validate(data)


class TestIntegrationsRepository:
    async def test_create_and_get_by_integration_id(self, repo):
        iid = f"int-{uuid.uuid4().hex}"
        created = await repo.create(_integration(iid, "Notion"))
        # _id is incidental; identity is integration_id, so the model id stays empty.
        assert created.id == ""
        assert created.integration_id == iid

        got = await repo.get(iid)
        assert got is not None
        assert got.name == "Notion"
        assert got.mcp_config is not None
        assert got.mcp_config.server_url == "https://mcp.example.com"

    async def test_get_missing_returns_none(self, repo):
        assert await repo.get(f"absent-{uuid.uuid4().hex}") is None

    async def test_find_by_id_prefix_case_insensitive(self, repo):
        iid = f"AbC-{uuid.uuid4().hex}"
        await repo.create(_integration(iid, "Prefixed"))
        found = await repo.find_by_id_prefix(iid[:5].lower())
        assert found is not None and found.integration_id == iid

    async def test_find_by_id_prefix_or_name_matches_id_prefix(self, repo):
        iid = f"pref-{uuid.uuid4().hex}"
        await repo.create(_integration(iid, "SomeName"))
        found = await repo.find_by_id_prefix_or_name(iid[:6])
        assert found is not None and found.integration_id == iid

    async def test_find_by_id_prefix_or_name_matches_exact_name(self, repo):
        iid = f"byname-{uuid.uuid4().hex}"
        unique_name = f"Exact {uuid.uuid4().hex}"
        await repo.create(_integration(iid, unique_name))
        found = await repo.find_by_id_prefix_or_name(unique_name)
        assert found is not None and found.integration_id == iid

    async def test_find_by_id_prefix_or_name_no_match(self, repo):
        await repo.create(_integration(f"x-{uuid.uuid4().hex}", "Nope"))
        assert await repo.find_by_id_prefix_or_name(f"missing-{uuid.uuid4().hex}") is None

    async def test_get_custom_and_for_user_guards(self, repo):
        owner = "owner-1"
        iid = f"cc-{uuid.uuid4().hex}"
        await repo.create(_integration(iid, "Owned", source="custom", created_by=owner))
        platform = f"pl-{uuid.uuid4().hex}"
        await repo.create(_integration(platform, "Platform", source="platform", created_by=owner))

        assert (await repo.get_custom(iid)).integration_id == iid
        assert await repo.get_custom(platform) is None  # source != custom
        assert (await repo.get_custom_for_user(iid, owner)).integration_id == iid
        assert await repo.get_custom_for_user(iid, "intruder") is None  # not owner

    async def test_get_public_and_by_creator(self, repo):
        owner = "creator-x"
        pub = f"gp-{uuid.uuid4().hex}"
        await repo.create(_integration(pub, "Pub", is_public=True, created_by=owner))
        priv = f"gpp-{uuid.uuid4().hex}"
        await repo.create(_integration(priv, "Priv", is_public=False, created_by=owner))

        assert (await repo.get_public(pub)).integration_id == pub
        assert await repo.get_public(priv) is None
        assert (await repo.get_by_creator(pub, owner)).integration_id == pub
        assert await repo.get_by_creator(pub, "someone-else") is None

    async def test_increment_clone_count(self, repo):
        iid = f"cl-{uuid.uuid4().hex}"
        await repo.create(_integration(iid, "Cloney", clone_count=0))
        await repo.increment_clone_count(iid)
        await repo.increment_clone_count(iid)
        assert (await repo.get(iid)).clone_count == 2

    async def test_set_mcp_auth_and_clear_tools(self, repo):
        iid = f"auth-{uuid.uuid4().hex}"
        await repo.create(
            _integration(
                iid,
                "Auther",
                tools=[{"name": "t1"}],
            )
        )
        assert await repo.set_mcp_auth(iid, True, "oauth") is True
        got = await repo.get(iid)
        assert got.mcp_config.requires_auth is True
        assert got.mcp_config.auth_type == "oauth"
        assert got.tools  # tools present before clear

        await repo.clear_tools(iid)
        assert (await repo.get(iid)).tools == []
        # No such integration → no update.
        assert await repo.set_mcp_auth(f"absent-{uuid.uuid4().hex}", True, "oauth") is False

    async def test_ensure_unique_slug_appends_suffix(self, repo):
        token = uuid.uuid4().hex
        first = await repo.ensure_unique_slug("My Tool", token, f"a-{uuid.uuid4().hex}")
        # Store it, then a different integration with the same name/category collides.
        await repo.create(
            _integration(f"s-{uuid.uuid4().hex}", "My Tool", is_public=True, slug=first)
        )
        second = await repo.ensure_unique_slug("My Tool", token, f"b-{uuid.uuid4().hex}")
        assert second != first
        assert second.startswith(first)

    async def test_publish_and_unpublish(self, repo):
        owner = "pub-owner"
        iid = f"pb-{uuid.uuid4().hex}"
        await repo.create(
            _integration(iid, "Publishable", source="custom", created_by=owner, is_public=False)
        )

        ok = await repo.publish(
            iid, created_by=owner, category="dev", slug=f"slug-{iid}", content=None, clone_count=3
        )
        assert ok is True
        got = await repo.get(iid)
        assert got.is_public is True
        assert got.slug == f"slug-{iid}"
        assert got.published_at is not None

        # Re-publish is a no-op (already public → guarded filter matches nothing).
        assert (
            await repo.publish(
                iid, created_by=owner, category="dev", slug="x", content=None, clone_count=3
            )
            is False
        )
        # Wrong creator can't publish.
        other = f"pb2-{uuid.uuid4().hex}"
        await repo.create(_integration(other, "Other", source="custom", created_by=owner))
        assert (
            await repo.publish(
                other, created_by="intruder", category="dev", slug="y", content=None, clone_count=0
            )
            is False
        )

        assert await repo.unpublish(iid) is True
        after = await repo.get(iid)
        assert after.is_public is False
        assert after.published_at is None

    async def test_delete_custom_is_owner_scoped(self, repo):
        owner = "owner-2"
        iid = f"cd-{uuid.uuid4().hex}"
        await repo.create(_integration(iid, "ToDelete", source="custom", created_by=owner))

        assert await repo.delete_custom(iid, "intruder") is False  # not owner
        assert await repo.get(iid) is not None  # still there
        assert await repo.delete_custom(iid, owner) is True
        assert await repo.get(iid) is None

    async def test_find_by_ids_any_source(self, repo):
        a = f"any-a-{uuid.uuid4().hex}"
        b = f"any-b-{uuid.uuid4().hex}"
        await repo.create(_integration(a, "A", source="custom", is_public=False))
        await repo.create(_integration(b, "B", source="platform", is_public=True))
        found = await repo.find_by_ids([a, b, f"missing-{uuid.uuid4().hex}"])
        assert {i.integration_id for i in found} == {a, b}

    async def test_store_and_get_tools_upserts(self, repo):
        iid = f"tools-{uuid.uuid4().hex}"
        # store_tools upserts a tools-only stub even with no integration doc yet.
        await repo.store_tools(iid, [IntegrationTool(name="t1", description="d1")])
        got = await repo.get_tools(iid)
        assert [t.name for t in got] == ["t1"]
        # Overwrites on the next store.
        await repo.store_tools(iid, [IntegrationTool(name="t2")])
        assert [t.name for t in await repo.get_tools(iid)] == ["t2"]
        # Missing integration → empty list, not error.
        assert await repo.get_tools(f"absent-{uuid.uuid4().hex}") == []

    async def test_store_tools_batch_and_all_with_tools(self, repo):
        a = f"ba-{uuid.uuid4().hex}"
        b = f"bb-{uuid.uuid4().hex}"
        await repo.create(_integration(a, "Aname", icon_url="https://a.png"))
        await repo.store_tools_batch(
            [(a, [IntegrationTool(name="ta")]), (b, [IntegrationTool(name="tb")])]
        )
        records = {r.integration_id: r for r in await repo.all_with_tools()}
        assert a in records and b in records
        assert records[a].name == "Aname"  # existing doc's name is preserved
        assert records[a].icon_url == "https://a.png"
        assert [t.name for t in records[a].tools] == ["ta"]

    async def test_heal_top_level_auth(self, repo):
        iid = f"heal-{uuid.uuid4().hex}"
        await repo.create(_integration(iid, "Heal", requires_auth=False, auth_type=None))
        await repo.heal_top_level_auth(iid, True, "oauth")
        got = await repo.get(iid)
        assert got.requires_auth is True
        assert got.auth_type == "oauth"

    async def test_find_custom_by_ids_filters_source(self, repo):
        custom_id = f"c-{uuid.uuid4().hex}"
        platform_id = f"p-{uuid.uuid4().hex}"
        await repo.create(_integration(custom_id, "Custom", source="custom"))
        await repo.create(_integration(platform_id, "Platform", source="platform"))

        found = await repo.find_custom_by_ids([custom_id, platform_id])
        assert [i.integration_id for i in found] == [custom_id]

    async def test_list_public_custom_newest_first_and_category(self, repo):
        await repo.create(
            _integration(
                f"old-{uuid.uuid4().hex}",
                "Old",
                is_public=True,
                category="dev",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await repo.create(
            _integration(
                f"new-{uuid.uuid4().hex}",
                "New",
                is_public=True,
                category="dev",
                created_at=datetime(2026, 2, 1, tzinfo=UTC),
            )
        )
        # Private + wrong category are excluded.
        await repo.create(_integration(f"priv-{uuid.uuid4().hex}", "Priv", is_public=False))
        await repo.create(
            _integration(f"other-{uuid.uuid4().hex}", "Other", is_public=True, category="comms")
        )

        listed = await repo.list_public_custom("dev")
        assert [i.name for i in listed] == ["New", "Old"]  # created_at desc

        all_public = await repo.list_public_custom()
        assert {i.name for i in all_public} == {"New", "Old", "Other"}

    async def test_search_public_matches_and_excludes(self, repo):
        hit = f"hit-{uuid.uuid4().hex}"
        excluded = f"exc-{uuid.uuid4().hex}"
        private = f"prv-{uuid.uuid4().hex}"
        await repo.create(
            _integration(hit, "Weather Radar", is_public=True, description="forecast")
        )
        await repo.create(
            _integration(excluded, "Weather Station", is_public=True, description="forecast")
        )
        await repo.create(_integration(private, "Weather Private", is_public=False))

        results = await repo.search_public(
            words=["weather"], query="weather", exclude_ids=[excluded], limit=10
        )
        ids = {i.integration_id for i in results}
        assert hit in ids
        assert excluded not in ids  # $nin
        assert private not in ids  # is_public gate

    async def test_search_public_respects_limit(self, repo):
        token = uuid.uuid4().hex
        for n in range(5):
            await repo.create(
                _integration(f"lim-{n}-{token}", f"Limitcase {token}", is_public=True)
            )
        results = await repo.search_public(words=[token], query=token, exclude_ids=[], limit=3)
        assert len(results) == 3

    async def test_find_public_by_ids(self, repo):
        pub = f"pub-{uuid.uuid4().hex}"
        priv = f"priv-{uuid.uuid4().hex}"
        await repo.create(_integration(pub, "Public", is_public=True))
        await repo.create(_integration(priv, "Private", is_public=False))
        found = await repo.find_public_by_ids([pub, priv])
        assert [i.integration_id for i in found] == [pub]

    async def test_get_public_by_slug(self, repo):
        iid = f"slug-{uuid.uuid4().hex}"
        slug = f"my-tool-{uuid.uuid4().hex}"
        await repo.create(_integration(iid, "Slugged", is_public=True, slug=slug))
        # A private doc with the same slug must not match.
        await repo.create(_integration(f"p-{uuid.uuid4().hex}", "Priv", is_public=False, slug=slug))

        got = await repo.get_public_by_slug(slug)
        assert got is not None
        assert got.integration_id == iid
        assert got.slug == slug
        assert got.creator is None  # no matching user in the fixture DB
        assert await repo.get_public_by_slug(f"absent-{uuid.uuid4().hex}") is None

    async def test_get_public_by_id_prefix(self, repo):
        iid = f"AbCdEf-{uuid.uuid4().hex}"
        await repo.create(_integration(iid, "Prefixed", is_public=True))
        got = await repo.get_public_by_id_prefix(iid[:6].lower())
        assert got is not None and got.integration_id == iid

    async def test_community_by_ids_and_creator_none(self, repo):
        a = f"a-{uuid.uuid4().hex}"
        b = f"b-{uuid.uuid4().hex}"
        await repo.create(_integration(a, "A", is_public=True))
        await repo.create(_integration(b, "B", is_public=True))
        results = await repo.community_by_ids([b, a])
        assert {i.integration_id for i in results} == {a, b}
        assert all(i.creator is None for i in results)

    async def test_community_search_count_and_page(self, repo):
        token = uuid.uuid4().hex
        for n in range(3):
            await repo.create(
                _integration(
                    f"cs-{n}-{token}",
                    f"Searchable {token}",
                    is_public=True,
                    clone_count=n,
                    published_at=datetime(2026, 1, n + 1, tzinfo=UTC),
                )
            )
        total = await repo.count_community_search(token, "all")
        assert total == 3
        page = await repo.community_search(token, "all", offset=0, limit=2)
        assert len(page) == 2
        # popular sort: highest clone_count first
        assert page[0].clone_count >= page[1].clone_count

    async def test_community_browse_sort_and_count(self, repo):
        cat = f"cat-{uuid.uuid4().hex}"
        await repo.create(
            _integration(
                f"br-a-{uuid.uuid4().hex}",
                "Alpha",
                is_public=True,
                category=cat,
                published_at=datetime(2026, 1, 1, tzinfo=UTC),
                clone_count=1,
            )
        )
        await repo.create(
            _integration(
                f"br-b-{uuid.uuid4().hex}",
                "Bravo",
                is_public=True,
                category=cat,
                published_at=datetime(2026, 2, 1, tzinfo=UTC),
                clone_count=9,
            )
        )
        # Unpublished (published_at None) is excluded from browse.
        await repo.create(
            _integration(f"br-c-{uuid.uuid4().hex}", "Charlie", is_public=True, category=cat)
        )

        assert await repo.count_community_browse(cat) == 2
        by_name = await repo.community_browse("name", cat, offset=0, limit=10)
        assert [i.name for i in by_name] == ["Alpha", "Bravo"]
        by_popular = await repo.community_browse("popular", cat, offset=0, limit=10)
        assert by_popular[0].name == "Bravo"  # highest clone_count first
