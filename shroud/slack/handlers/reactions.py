import datetime
from typing import Any, cast
from slack_sdk import WebClient
from shroud.slack import app
from shroud.utils import db

# Listen for reaction_added events to remove :hourglass: if :white_check_mark: or :x: is added
@app.event("reaction_added")
def handle_reaction_added(event, client: WebClient):
    reaction = event.get("reaction")
    item = event.get("item", {})
    channel = item.get("channel")
    ts = item.get("ts")
    # Only act on :white_check_mark: or :x:
    if reaction in ("white_check_mark", "x"):
        # Only care if the message thread is in the database
        record = db.get_message_by_ts(ts)
        if not record:
            return
        # Remove :hourglass: reaction if present
        try:
            client.reactions_remove(
                channel=channel,
                name="hourglass",
                timestamp=ts
            )
        except Exception as e:
            print(f"Failed to remove :hourglass: reaction: {e}")
        # Set resolve_time in db to the time difference between forward and now
        try:
            forwarded_time = record["fields"].get("forwarded_ts")
            if forwarded_time:
                fwd_dt = datetime.datetime.fromtimestamp(float(forwarded_time), tz=datetime.timezone.utc)
                now_dt = datetime.datetime.now(datetime.timezone.utc)
                time_diff = (now_dt - fwd_dt).total_seconds()
                formatted_time = str(datetime.timedelta(seconds=int(time_diff)))
                db.get_table().update(record["id"], {"resolve_time": formatted_time})
        except Exception as e:
            print(f"Failed to set resolve_time: {e}")

# Listen for reaction_removed events to re-add :hourglass: if :white_check_mark: or :x: is removed and neither is present
@app.event("reaction_removed")
def handle_reaction_removed(event, client: WebClient):
    reaction = event.get("reaction")
    item = event.get("item", {})
    channel = item.get("channel")
    ts = item.get("ts")
    # Only act if :white_check_mark: or :x: is removed
    if reaction in ("white_check_mark", "x"):
        # Only care if the message thread is in the database
        record = db.get_message_by_ts(ts)
        if not record:
            return
        # Fetch current reactions for the message
        try:
            resp = client.reactions_get(channel=channel, timestamp=ts)
            data = cast(dict[str, Any], resp.data)
            message_data = cast(dict[str, Any], data.get("message", {}))
            reactions = cast(list[dict[str, Any]], message_data.get("reactions", []))
            # Count all check mark and x reactions
            check_count = next((r["count"] for r in reactions if r["name"] == "white_check_mark"), 0)
            x_count = next((r["count"] for r in reactions if r["name"] == "x"), 0)
            if check_count == 0 and x_count == 0:
                # Re-add :hourglass: if neither is present
                client.reactions_add(
                    channel=channel,
                    name="hourglass",
                    timestamp=ts
                )
                # Set resolve_time in db to blank string
                try:
                    db.get_table().update(record["id"], {"resolve_time": ""})
                except Exception as e:
                    print(f"Failed to reset resolve_time: {e}")
        except Exception as e:
            print(f"Failed to re-add :hourglass: reaction: {e}")
