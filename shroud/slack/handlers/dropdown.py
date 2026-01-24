from typing import Any, cast
from slack_sdk import WebClient
from shroud import settings
from shroud.slack import app
from shroud.utils import db, utils

# Listener for the dropdown selection
@app.action("report_forwarding")
def handle_selection(ack, body):
    ack()

    selected_option = body["actions"][0]["selected_option"]["value"]
    db.save_selection(selection_ts=body["message"]["ts"], selection=selected_option)


# Listener for the submit button
@app.action("submit_forwarding")
def handle_submission(ack, body, say, client: WebClient):
    ack()

    user_id = body["user"]["id"]

    # Get the user's selection
    message_record = db.get_message_by_ts(body["message"]["ts"])
    if message_record is None:
        return
    user_selection = message_record.get("fields", {}).get("selection", None)
    if user_selection is not None:
        message = utils.get_message_by_ts(
            ts=message_record["fields"]["dm_ts"],
            channel=message_record["fields"]["dm_channel"],
            client=client,
        )
        if message is None:
            return
        original_text = message["text"]
        attachments = message.get("attachments", [])

        # TODO: Update the message instead of sending a new one (perhaps)
        # if user_selection == "anonymous":
        #     # Forward anonymously
        #     say("Anonymously forwarding the report...")
        # else:
        #     say("Forwarding the report with your username...")

        # Update the original message to prevent reuse
        app.client.chat_update(
            channel=message_record["fields"]["dm_channel"],
            ts=message_record["fields"]["selection_ts"],
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{'This report has been submitted' if user_selection == "with_username" else 'This report has been submitted anonymously'}. We've received your report and should get back to you within a couple hours.",
                    },
                }
            ],
            text="Report submitted",
        )

        post_resp = client.chat_postMessage(
            channel=settings.channel,
            text=original_text,
            attachments=attachments,
            username=utils.get_name(user_id, client)
            if user_selection == "with_username"
            else None,
            icon_url=utils.get_profile_picture_url(user_id, client)
            if user_selection == "with_username"
            else None,
        )
        post_data = cast(dict[str, Any], post_resp.data)
        forwarded_ts = str(post_data.get("ts", ""))
        # Add :hourglass: reaction to the forwarded message
        client.reactions_add(
            channel=settings.channel,
            name="hourglass",
            timestamp=forwarded_ts
        )
        # Add :white_check_mark: reaction to the original user's message
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
    else:
        say("Please select an option before submitting.")


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
        db.get_table().delete(message_record["id"])

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

