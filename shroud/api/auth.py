import jwt
from datetime import datetime
from fastapi import Header, HTTPException
from shroud import settings
from shroud.utils import db


def verify_token(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, settings.api_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    app_slug = payload.get("sub")
    iat = payload.get("iat")
    if not app_slug:
        raise HTTPException(status_code=401, detail="Missing sub claim")

    record = db.get_api_client(app_slug)
    if record:
        revoked_before = record["fields"].get("revoked_before")
        if revoked_before and iat is not None:
            revoked_ts = datetime.fromisoformat(revoked_before.replace("Z", "+00:00")).timestamp()
            if iat < revoked_ts:
                raise HTTPException(status_code=401, detail="Token revoked")

    return app_slug
