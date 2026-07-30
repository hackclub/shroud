import os
import random
import string
import requests
from slack_sdk import WebClient
from shroud import settings
from shroud.utils import db
from typing import Any, TYPE_CHECKING, cast
if TYPE_CHECKING:
    from shroud.slack.handlers.incoming_message import MessageEvent



def get_message_by_ts(ts: str, channel: str, client: WebClient) -> dict[str, Any] | None:
    try:
        resp = client.conversations_history(
            channel=channel, oldest=ts, latest=ts, inclusive=True, limit=1
        )
        data = cast(dict[str, Any], resp.data)
        messages = cast(list[dict[str, Any]], data.get("messages", []))
        return messages[0]
    except IndexError:
        # This might be because it's a threaded message
        try:
            resp = client.conversations_replies(
                channel=channel, ts=ts, oldest=ts, inclusive=True, limit=1
            )
            data = cast(dict[str, Any], resp.data)
            messages = cast(list[dict[str, Any]], data.get("messages", []))
            return messages[0]
        except IndexError:
            return None



def get_profile_picture_url(user_id: str, client: WebClient) -> str:
    user_info = client.users_info(user=user_id)
    data = cast(dict[str, Any], user_info.data)
    user_data = cast(dict[str, Any], data.get("user", {}))
    return str(user_data.get("profile", {}).get("image_512", ""))


def get_name(user_id: str, client: WebClient) -> str:
    user_info = client.users_info(user=user_id)
    data = cast(dict[str, Any], user_info.data)
    user_data = cast(dict[str, Any], data.get("user", {}))
    return str(user_data.get("real_name", ""))


IDENTITY_BLOCK_ID = "report_forwarding_block"
IDENTITY_ACTION_ID = "report_forwarding"
IDENTITY_OPTION = {
    "text": {"type": "plain_text", "text": "Include my username"},
    "description": {
        "type": "plain_text",
        "text": "FD will see who filed this report. Leave unchecked to stay anonymous.",
    },
    "value": "with_username",
}


def begin_forward(message: "MessageEvent", client: WebClient) -> None:
    default_selection = "with_username" if settings.disable_anonymous else "anonymous"

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "Ready to send this report to FD with your username."
                    if settings.disable_anonymous
                    else "Ready to send this report to FD. It'll be sent anonymously unless you check the box below."
                ),
            },
        }
    ]
    if not settings.disable_anonymous:
        blocks.append(
            {
                "type": "actions",
                "block_id": IDENTITY_BLOCK_ID,
                "elements": [
                    {
                        "type": "checkboxes",
                        "action_id": IDENTITY_ACTION_ID,
                        "options": [IDENTITY_OPTION],
                    }
                ],
            }
        )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Submit"},
                    "style": "primary",
                    "action_id": "submit_forwarding",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "style": "danger",
                    "action_id": "cancel_forwarding",
                },
            ],
        }
    )

    selection_prompt = client.chat_postMessage(
        channel=message.channel,
        text="Submit this report to FD",
        thread_ts=message.ts,
        blocks=blocks,
    )
    prompt_data = cast(dict[str, Any], selection_prompt.data)
    selection_ts = str(prompt_data.get("ts", ""))

    db.save_forward_start(
        dm_ts=message.ts,
        content=message.content or "",
        selection_ts=selection_ts,
        dm_channel=message.channel,
        selection=default_selection,
    )

# def is_thread(event: Dict[str, Any]) -> bool:
#     return "thread_ts" in event
#     # return "thread_ts" in event or "thread_ts" in event.get("previous_message", {})

def report_thread_channels() -> list[str]:
    channels: list[str] = []
    seen: set[str] = set()
    for channel in [
        settings.channel,
        *(settings.old_channels or []),
        settings.old_channel,
    ]:
        if channel and channel not in seen:
            seen.add(channel)
            channels.append(channel)
    return channels

def get_forwarded_channel(forwarded_ts: str, client: WebClient) -> str:
    for channel in report_thread_channels():
        try:
            if get_message_by_ts(forwarded_ts, channel, client):
                return channel
        except Exception:
            pass
    return settings.channel


_VALID_ATTACHMENT_KEYS = {
    "fallback", "color", "pretext", "author_name", "author_link", "author_icon",
    "title", "title_link", "text", "fields", "image_url", "thumb_url",
    "footer", "footer_icon", "ts", "mrkdwn_in", "actions", "callback_id",
    "attachment_type",
}

def sanitize_attachments(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in a.items() if k in _VALID_ATTACHMENT_KEYS} for a in attachments]


def forward_files(files: list[dict[str, Any]], channel: str, thread_ts: str, client: WebClient) -> None:
    for file_data in files:
        url = file_data.get("url_private_download") or file_data.get("url_private")
        if not url:
            continue
        og = file_data.get("name", "file")
        ext = os.path.splitext(og)[1]
        filename = f"{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}{ext}"
        response = requests.get(url, headers={"Authorization": f"Bearer {settings.slack_bot_token}"})
        response.raise_for_status()
        client.files_upload_v2(
            channel=channel,
            thread_ts=thread_ts,
            file=response.content,
            filename=filename,
        )


def auto_forward(message: "MessageEvent", client: WebClient) -> None:
    post_resp = client.chat_postMessage(
        channel=settings.channel,
        text=message.content or "(forwarded message)",
        attachments=sanitize_attachments(message.attachments) if message.attachments else None,
        unfurl_links=True,
        unfurl_media=True,
    )
    post_data = cast(dict[str, Any], post_resp.data)
    forwarded_ts = str(post_data.get("ts", ""))

    try:
        client.reactions_add(channel=settings.channel, name="hourglass", timestamp=forwarded_ts)
    except Exception as e:
        print(f"Failed to add hourglass reaction: {e}")

    try:
        client.reactions_add(channel=message.channel, name="white_check_mark", timestamp=message.ts)
    except Exception as e:
        print(f"Failed to add checkmark reaction to DM: {e}")

    db.save_forward_start(dm_ts=message.ts, content=message.content or "", dm_channel=message.channel, is_auto_forward=True)
    db.finish_forward(dm_ts=message.ts, forwarded_ts=forwarded_ts)


def apply_command_prefix(command: str) -> str:
    command = f"/{settings.app_name}-{command}"
    print(f"Adding command {command}")
    return command
