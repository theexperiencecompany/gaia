from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.api.v1.endpoints.bot import validate_platform, verify_bot_api_key
from app.db.mongodb.collections import users_collection

router = APIRouter()


@router.get("/link/{platform}")
async def link_platform_account(
    platform: str, request: Request, platform_user_id: str
) -> HTMLResponse:
    validate_platform(platform)

    if not getattr(request.state, "authenticated", False):
        return HTMLResponse(
            content="""
<!DOCTYPE html>
<html>
<head>
    <title>Authentication Required</title>
    <style>
        body {
            font-family: system-ui, -apple-system, sans-serif;
            text-align: center;
            padding-top: 100px;
            background: #0a0a0a;
            color: #fafafa;
        }
        h1 { color: #ef4444; }
        a { color: #3b82f6; }
    </style>
</head>
<body>
    <h1>Authentication Required</h1>
    <p>Please log in to GAIA first, then click the link again.</p>
    <p><a href="/">Go to GAIA</a></p>
</body>
</html>
""",
            status_code=401,
        )

    user = request.state.user
    user_id = user.get("user_id") if user else None

    if not user_id:
        raise HTTPException(status_code=401, detail="Could not identify user")

    result = await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {f"platform_links.{platform}": platform_user_id}},
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
async def check_auth_status(
    platform: str,
    platform_user_id: str,
    _: None = Depends(verify_bot_api_key),
) -> dict:
    validate_platform(platform)

    user = await users_collection.find_one(
        {f"platform_links.{platform}": platform_user_id}
    )
    return {
        "authenticated": user is not None,
        "platform": platform,
        "platform_user_id": platform_user_id,
    }
