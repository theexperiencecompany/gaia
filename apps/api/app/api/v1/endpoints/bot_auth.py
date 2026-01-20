from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.db.mongodb.collections import users_collection

router = APIRouter()


@router.get("/link/{platform}")
async def link_platform_account(
    platform: str, user_id: str = Query(...), platform_user_id: str = Query(...)
) -> HTMLResponse:
    if platform not in ["discord", "slack", "telegram"]:
        raise HTTPException(status_code=400, detail="Invalid platform")

    result = await users_collection.update_one(
        {"user_id": user_id}, {"$set": {f"platform_links.{platform}": platform_user_id}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return HTMLResponse(
        content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Account Linked</title>
    <style>
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            text-align: center;
            padding-top: 100px;
            background: #0a0a0a;
            color: #fafafa;
        }}
        h1 {{ color: #22c55e; }}
    </style>
</head>
<body>
    <h1>Account Linked</h1>
    <p>Your {platform.title()} account has been linked to GAIA.</p>
    <p>You can close this window and return to {platform.title()}.</p>
</body>
</html>
    """
    )


@router.get("/status/{platform}/{platform_user_id}")
async def check_auth_status(platform: str, platform_user_id: str) -> dict:
    user = await users_collection.find_one(
        {f"platform_links.{platform}": platform_user_id}
    )
    return {
        "authenticated": user is not None,
        "platform": platform,
        "platform_user_id": platform_user_id,
    }
