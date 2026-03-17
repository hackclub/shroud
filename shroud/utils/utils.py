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
            channel=channel, oldest=ts, inclusive=True, limit=1
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


def begin_forward(message: "MessageEvent", client: WebClient) -> None:
    selection_prompt = client.chat_postMessage(
        channel=message.channel,
        text="Select how this message should be forwarded",
        thread_ts=message.ts,  # Thread the prompt under the user's message
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Do you want to forward this report anonymously or with your username?",
                },
                "accessory": {
                    "type": "static_select",
                    "action_id": "report_forwarding",
                    "placeholder": {"type": "plain_text", "text": "Choose an option"},
                    "options": [
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "Forward Anonymously",
                            },
                            "value": "anonymous",
                        },
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "Forward with Username",
                            },
                            "value": "with_username",
                        },
                    ],
                },
            },
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
                    }
                ],
            },
        ],
    )
    prompt_data = cast(dict[str, Any], selection_prompt.data)
    selection_ts = str(prompt_data.get("ts", ""))

    db.save_forward_start(
        dm_ts=message.ts,
        content=message.content or "",
        selection_ts=selection_ts,
        dm_channel=message.channel
    )

# def is_thread(event: Dict[str, Any]) -> bool:
#     return "thread_ts" in event
#     # return "thread_ts" in event or "thread_ts" in event.get("previous_message", {})

def forward_files(files: list[dict[str, Any]], channel: str, thread_ts: str, client: WebClient) -> None:
    for file_data in files:
        url = file_data.get("url_private_download") or file_data.get("url_private")
        if not url:
            continue
        filename = file_data.get("name", "file")
        response = requests.get(url, headers={"Authorization": f"Bearer {settings.slack_bot_token}"})
        response.raise_for_status()
        client.files_upload_v2(
            channel=channel,
            thread_ts=thread_ts,
            file=response.content,
            filename=filename,
        )


def apply_command_prefix(command: str) -> str:
    command = f"/{settings.app_name}-{command}"
    print(f"Adding command {command}")
    return command