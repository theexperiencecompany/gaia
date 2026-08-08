"""Mint a brand-new user with zero history — the exact state bugs 1 & 2 fire in."""
import asyncio, httpx

API = "http://localhost:9870/api/v1"

async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{API}/dev/users", json={"email": "firstvisit@gaia.local", "name": "First"})
        print("mint:", r.status_code, r.text[:120])
        s = await c.get(f"{API}/usage/summary", headers={"X-Dev-User": "firstvisit@gaia.local"})
        h = await c.get(f"{API}/usage/history?days=30", headers={"X-Dev-User": "firstvisit@gaia.local"})
        a = await c.get(f"{API}/usage/activity?days=365", headers={"X-Dev-User": "firstvisit@gaia.local"})
        print("summary:", s.status_code, "| history rows:", len(h.json()), "| activity total:", a.json().get("total"), "tier:", a.json().get("tier"))

asyncio.run(main())
