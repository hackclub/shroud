import sys
import time
import secrets
import dotenv

dotenv.load_dotenv()

from shroud import settings

if len(sys.argv) < 2:
    print("Usage: python scripts/issue_token.py <app_slug> [--gen-secret]")
    sys.exit(1)

if "--gen-secret" in sys.argv:
    print(secrets.token_hex(32))
    sys.exit(0)

if not settings.get("api_secret"):
    print("Error: SHROUD__API_SECRET is not set")
    print("Generate one with: python scripts/issue_token.py --gen-secret")
    sys.exit(1)

try:
    import jwt
except ImportError:
    print("Error: PyJWT not installed. Run: uv sync")
    sys.exit(1)

app_slug = sys.argv[1]
token = jwt.encode(
    {"sub": app_slug, "iat": int(time.time())},
    settings.api_secret,
    algorithm="HS256",
)
print(token)
