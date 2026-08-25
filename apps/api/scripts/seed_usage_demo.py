"""Local-dev seed for the usage settings page.

Creates a dev user (matched by DEV_AUTH_BYPASS_EMAIL), a year of activity for the
heatmap/badge, a Pro subscription, and realistic Redis usage + cost counters so
every panel on /settings/usage has real data. Idempotent per (user, date/key).

Run:  uv run --group backend python scripts/seed_usage_demo.py [email] [free|pro]
"""

from datetime import UTC, datetime, timedelta
import math
import sys

import pymongo
import redis

EMAIL = sys.argv[1] if len(sys.argv) > 1 else "aryan.k.randeriya@gmail.com"
PLAN = sys.argv[2] if len(sys.argv) > 2 else "pro"
NAME = "Aryan"

mongo = pymongo.MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=4000)
db = mongo.get_database("GAIA")  # app hardcodes db_name="GAIA"
r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)

# --- 1. dev user (upsert by email) -----------------------------------------
now = datetime.now(UTC)
db["users"].update_one(
    {"email": EMAIL},
    {
        "$setOnInsert": {"email": EMAIL, "name": NAME, "created_at": now, "picture": ""},
        "$set": {"updated_at": now},
    },
    upsert=True,
)
user = db["users"].find_one({"email": EMAIL})
uid = str(user["_id"])
print(f"user: {EMAIL}  user_id={uid}  plan={PLAN}")

# --- 2. a year of daily activity (deterministic, realistic) ----------------
# Per-action LLM cost: free rides the cheap model; pro runs heavier agent loops.
# Free stays under FREE_DAILY_COST_BUDGET_USD (0.05) at the seeded ~7-14
# actions/day, so the demo shows a realistic partially-used gauge, not the wall.
COST_PER_ACTION = 0.003 if PLAN == "free" else 0.010
db["usage_daily"].delete_many({"user_id": uid})
today = now.replace(hour=0, minute=0, second=0, microsecond=0)
rows = []
total = 0
for i in range(365):
    d = today - timedelta(days=364 - i)
    dow = d.weekday()  # 0=Mon
    # weekday base higher than weekend; gentle seasonal wave; deterministic jitter
    base = 22 if dow < 5 else 9
    wave = 1 + 0.35 * math.sin(i / 30.0)
    jitter = ((i * 7919) % 13) - 5
    count = max(0, round(base * wave) + jitter)
    # scattered fully-inactive days, but keep the last 11 days a live streak
    if (i * 104729) % 9 == 0 and i < 354:
        count = 0
    if i >= 354:
        count = max(count, 6)
    if count:
        rows.append(
            {
                "user_id": uid,
                "date": d.strftime("%Y-%m-%d"),
                "count": count,
                "cost": round(count * COST_PER_ACTION * (1 + ((i * 31) % 7) / 10), 6),
            }
        )
        total += count
if rows:
    db["usage_daily"].insert_many(rows)
print(f"usage_daily: {len(rows)} active days, {total} total actions (+cost)")

# --- 2b. 30 days of usage_snapshots (drives Day-by-day + monthly trend) ----
# Daily chat counts derived from the heatmap rows so the two charts agree.
day_counts = {r["date"]: r["count"] for r in rows}
chat_day_limit = 15 if PLAN == "free" else 0
chat_month_limit = 200 if PLAN == "free" else 60000
db["usage_snapshots"].delete_many({"user_id": uid})
snaps = []
month_cum: dict[str, int] = {}
for i in range(30):
    d = today - timedelta(days=29 - i)
    date_key = d.strftime("%Y-%m-%d")
    # chat messages that day: scale heatmap actions down, cap at the free limit
    raw = day_counts.get(date_key, 0)
    used = min(raw // 2, chat_day_limit) if PLAN == "free" else raw // 2
    mkey = d.strftime("%Y-%m")
    month_cum[mkey] = month_cum.get(mkey, 0) + used
    day_reset = d + timedelta(days=1)
    month_reset = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
    snaps.append(
        {
            "user_id": uid,
            "plan_type": PLAN,
            "features": [
                {
                    "feature_key": "chat_messages",
                    "feature_title": "Chat Messages",
                    "period": "day",
                    "used": used,
                    "limit": chat_day_limit,
                    "reset_time": day_reset,
                    "updated_at": d,
                },
                {
                    "feature_key": "chat_messages",
                    "feature_title": "Chat Messages",
                    "period": "month",
                    "used": month_cum[mkey],
                    "limit": chat_month_limit,
                    "reset_time": month_reset,
                    "updated_at": d,
                },
            ],
            "credits": [],
            "snapshot_date": d,
            "created_at": d,
        }
    )
db["usage_snapshots"].insert_many(snaps)
print(f"usage_snapshots: {len(snaps)} days (chat day limit={chat_day_limit})")

# --- 3. subscription (pro => active doc; free => none) ---------------------
db["subscriptions"].delete_many({"user_id": uid})
if PLAN == "pro":
    db["subscriptions"].insert_one(
        {
            # Synthetic but schema-valid: SubscriptionDocument requires
            # dodo_subscription_id (webhooks key on it).
            "dodo_subscription_id": f"sub_demo_{uid}",
            "user_id": uid,
            "status": "active",
            "product_id": "pro",
            "created_at": now,
            "updated_at": now,
        }
    )
print(f"subscription: {'active (PRO)' if PLAN == 'pro' else 'none (FREE)'}")

# --- 4. Redis live counters — MUST agree with today's snapshot -------------
# The hero gauge reads live Redis while the charts read snapshots; the page is
# only coherent when today's live values equal today's snapshot values.
day_win = now.strftime("%Y%m%d")
month_win = now.strftime("%Y%m")
today_key = today.strftime("%Y-%m-%d")
month_prefix = today.strftime("%Y-%m")

chat_today = next(
    (s["features"][0]["used"] for s in snaps if s["created_at"].strftime("%Y-%m-%d") == today_key),
    0,
)
chat_month_cum = month_cum.get(month_prefix, 0)

# Per-feature counts (day, month) — drives Tools + the monthly stat.
feature_day = {
    "chat_messages": chat_today,
    "web_search": 13,
    "webpage_fetch": 2,
    "file_analysis": 2,
    "deep_research": 1,
    "calendar_management": 3,
    "mail_actions": 1,
    "todo_operations": 8,
    "notes": 4,
    "memory": 6,
    "generate_image": 1,
    "reminder_operations": 2,
}
# NOTE: the app builds keys with the enum *repr* ("RateLimitPeriod.DAY"), not
# "day" — see tiered_rate_limiter._get_redis_key. Match it exactly.
for feat, used in feature_day.items():
    r.set(f"rate_limit:{uid}:{feat}:RateLimitPeriod.DAY:{day_win}", used)
    month_used = chat_month_cum if feat == "chat_messages" else used * 11 + 7
    r.set(f"rate_limit:{uid}:{feat}:RateLimitPeriod.MONTH:{month_win}", month_used)

# Cost budget windows: derived from the same per-day costs the rollup holds.
cost_today = next((row["cost"] for row in rows if row["date"] == today_key), 0.0)
cost_month = sum(row["cost"] for row in rows if row["date"].startswith(month_prefix))
r.set(f"cost_budget:{uid}:day:{day_win}", f"{cost_today:.6f}")
r.set(f"cost_budget:{uid}:month:{month_win}", f"{cost_month:.6f}")
print(
    f"redis: chat {chat_today}/day {chat_month_cum}/mo; "
    f"cost ${cost_today:.3f}/day ${cost_month:.2f}/mo"
)

print(f"\nDONE. Set DEV_AUTH_BYPASS_EMAIL={EMAIL} and restart the API.")
