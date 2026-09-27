from typing import Any, cast
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from shroud import settings
from shroud.slack import app
from shroud.utils import db


def _get_permalink(channel: str, ts: str, client: WebClient) -> str | None:
    try:
        resp = client.chat_getPermalink(channel=channel, message_ts=ts)
        return cast(dict[str, Any], resp.data).get("permalink")
    except SlackApiError as e:
        print(f"Failed to fetch permalink for reported message: {e}")
        return None


def _handle_report_shortcut(ack, body: dict[str, Any], client: WebClient, anonymous: bool) -> None:
    ack()

    reporter = body["user"]["id"]
    message = body["message"]
    origin_channel = body["channel"]["id"]
    reported_ts = message["ts"]
    reported_user = message.get("user")
    original_text = message.get("text", "")

    if anonymous and settings.disable_anonymous:
        client.chat_postEphemeral(
            channel=origin_channel,
            user=reporter,
            text="Anonymous reporting is disabled; please use \"Report and include my name\" instead.",
        )
        return

    permalink = _get_permalink(origin_channel, reported_ts, client)

    fd_lines = [
        f"🚩 New report on a message from <@{reported_user}> in <#{origin_channel}>"
        if reported_user
        else f"🚩 New report on a message in <#{origin_channel}>",
    ]
    if not anonymous:
        fd_lines.append(f"Reported by <@{reporter}>")
    if original_text:
        fd_lines.append(f">{original_text}")
    if permalink:
        fd_lines.append(permalink)
    fd_text = "\n".join(fd_lines)

    try:
        dm_open = client.conversations_open(users=reporter)
        dm_channel = cast(dict[str, Any], dm_open.data)["channel"]["id"]

        anon_word = "are" if anonymous else "aren't"
        dm_resp = client.chat_postMessage(
            channel=dm_channel,
            text=(
                "Hi! Your message has been reported to the Fire Department, which "
                "moderates the Slack. You can use this thread to talk with us! "
                f"You {anon_word} anonymous."
            ),
        )
        dm_ts = str(cast(dict[str, Any], dm_resp.data)["ts"])

        post_resp = client.chat_postMessage(
            channel=settings.channel,
            text=fd_text,
            unfurl_links=False,
            unfurl_media=False,
        )
        forwarded_ts = str(cast(dict[str, Any], post_resp.data)["ts"])

        try:
            client.reactions_add(channel=settings.channel, name="hourglass", timestamp=forwarded_ts)
        except Exception as e:
            print(f"Failed to add hourglass reaction: {e}")

        db.save_forward_start(
            dm_ts=dm_ts,
            content=original_text,
            dm_channel=dm_channel,
            selection="anonymous" if anonymous else "with_username",
        )
        db.finish_forward(dm_ts=dm_ts, forwarded_ts=forwarded_ts)
    except db.BackendUnavailable as e:
        print(f"ERROR: datastore unavailable; report shortcut skipped: {e}")
        client.chat_postEphemeral(
            channel=origin_channel,
            user=reporter,
            text="⚠️ The report system is temporarily unavailable. Please try again in a few minutes.",
        )
        return

    client.chat_postEphemeral(
        channel=origin_channel,
        user=reporter,
        text="Report submitted. Check your DMs to continue the conversation with FD.",
    )


@app.shortcut("report_anonymous")
def handle_report_anonymous(ack, body, client: WebClient):
    _handle_report_shortcut(ack, body, client, anonymous=True)


@app.shortcut("report_with_name")
def handle_report_with_name(ack, body, client: WebClient):
    _handle_report_shortcut(ack, body, client, anonymous=False)
