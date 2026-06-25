import jwt
from fastapi import Header, HTTPException
from shroud import settings


def verify_token(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, settings.api_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    app_slug = payload.get("sub")
    if not app_slug:
        raise HTTPException(status_code=401, detail="Missing sub claim")

    return app_slug
