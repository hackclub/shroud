from typing import cast, Any
from fastapi import FastAPI, Depends
from pydantic import BaseModel
from slack_sdk import WebClient
from shroud.api.auth import verify_token
from shroud.utils import db
from shroud import settings

api_app = FastAPI()


class ReportRequest(BaseModel):
    content: str
    blocks: list[dict[str, Any]] | None = None


@api_app.post("/api/v1/reports")
def create_report(body: ReportRequest, source: str = Depends(verify_token)):
    client = WebClient(token=settings.slack_bot_token)

    resp = client.chat_postMessage(
        channel=settings.channel,
        text=body.content,
        blocks=body.blocks,
        unfurl_links=True,
        unfurl_media=True,
    )
    resp_data = cast(dict[str, Any], resp.data)
    forwarded_ts = str(resp_data.get("ts", ""))

    try:
        client.reactions_add(channel=settings.channel, name="hourglass", timestamp=forwarded_ts)
    except Exception as e:
        print(f"Failed to add hourglass reaction: {e}")

    db.save_api_report(content=body.content, forwarded_ts=forwarded_ts, source=source)

    return {"forwarded_ts": forwarded_ts}
