from typing import Any, cast
from slack_sdk import WebClient
from shroud import settings
from shroud.slack import app
from shroud.utils import db, utils

def _selection_from_action(action: dict[str, Any]) -> str | None:
    if "selected_options" in action:
        selected = action.get("selected_options") or []
        return (
            "with_username"
            if any(o.get("value") == "with_username" for o in selected)
            else "anonymous"
        )
    selected_option = action.get("selected_option")
    if selected_option:
        return str(selected_option.get("value"))
    return None


def _selection_from_state(body: dict[str, Any]) -> str | None:
    action = (
        body.get("state", {})
        .get("values", {})
        .get(utils.IDENTITY_BLOCK_ID, {})
        .get(utils.IDENTITY_ACTION_ID)
    )
    return _selection_from_action(action) if action else None


@app.action("report_forwarding")
def handle_selection(ack, body):
    ack()

    selection = _selection_from_action(body["actions"][0])
    if selection is None:
        return
    try:
        db.save_selection(selection_ts=body["message"]["ts"], selection=selection)
    except ValueError:
        print("INFO: no record for the toggled report prompt; ignoring the selection.")


# Listener for the submit button
@app.action("submit_forwarding")
def handle_submission(ack, body, client: WebClient):
    ack()

    user_id = body["user"]["id"]

    message_record = db.get_message_by_ts(body["message"]["ts"])
    if message_record is None:
        return
    if message_record["fields"].get("forwarded_ts"):
        return
    user_selection = (
        _selection_from_state(body)
        or message_record.get("fields", {}).get("selection")
        or ("with_username" if settings.disable_anonymous else "anonymous")
    )
    with_username = user_selection == "with_username"

    message = utils.get_message_by_ts(
        ts=message_record["fields"]["dm_ts"],
        channel=message_record["fields"]["dm_channel"],
        client=client,
    )
    if message is None:
        return
    original_text = message["text"]
    original_attachments = message.get("attachments", [])

    app.client.chat_update(
        channel=message_record["fields"]["dm_channel"],
        ts=message_record["fields"]["selection_ts"],
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{'This report has been submitted' if with_username else 'This report has been submitted anonymously'}. We've received your report and should get back to you within a couple hours.",
                },
            }
        ],
        text="Report submitted",
    )

    post_resp = client.chat_postMessage(
        channel=settings.channel,
        text=original_text or "(forwarded message)",
        attachments=utils.sanitize_attachments(original_attachments) if original_attachments else None,
        unfurl_links=True,
        unfurl_media=True,
        username=utils.get_name(user_id, client) if with_username else None,
        icon_url=utils.get_profile_picture_url(user_id, client) if with_username else None,
    )
    post_data = cast(dict[str, Any], post_resp.data)
    forwarded_ts = str(post_data.get("ts", ""))
    utils.forward_files(message.get("files", []), settings.channel, forwarded_ts, client)
    client.reactions_add(
        channel=settings.channel,
        name="hourglass",
        timestamp=forwarded_ts
    )
    try:
        client.reactions_add(
            channel=message_record["fields"]["dm_channel"],
            name="white_check_mark",
            timestamp=message_record["fields"]["dm_ts"]
        )
    except Exception as e:
        print(f"Failed to add checkmark reaction to original message: {e}")
    db.finish_forward(
        dm_ts=message_record["fields"]["dm_ts"], forwarded_ts=forwarded_ts
    )
    client.chat_postEphemeral(
        channel=message_record["fields"]["dm_channel"],
        user=user_id,
        text="Message content forwarded. Any replies to the forwarded message will be sent back to you as a threaded reply. If you wish to add additional context, reply in the thread.",
    )


# Listener for the cancel button
@app.action("cancel_forwarding")
def handle_cancellation(ack, body, client: WebClient):
    ack()

    user_id = body["user"]["id"]
    selection_ts = body["message"]["ts"]

    try:
        # Get the message record to find the DM channel and original message
        message_record = db.get_message_by_ts(selection_ts)
        if message_record is None:
            client.chat_postEphemeral(
                channel=body["channel"]["id"],
                user=user_id,
                text="Report not found or already processed."
            )
            return

        # Check if the report has already been forwarded
        if message_record["fields"].get("forwarded_ts"):
            client.chat_postEphemeral(
                channel=body["channel"]["id"],
                user=user_id,
                text="Cannot cancel a report that has already been forwarded."
            )
            return

        # Update the selection message to show cancellation
        app.client.chat_update(
            channel=message_record["fields"]["dm_channel"],
            ts=selection_ts,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "This report has been cancelled.",
                    },
                }
            ],
            text="Report cancelled",
        )

        # Delete the incomplete database entry
        db.delete_record(message_record["id"])

        # Send confirmation to the user
        client.chat_postEphemeral(
            channel=message_record["fields"]["dm_channel"],
            user=user_id,
            text="Report has been cancelled successfully.",
        )

    except Exception as e:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text=f"An unexpected error occurred: {str(e)}"
        )

