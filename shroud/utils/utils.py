from slack_sdk import WebClient
from shroud import settings
from shroud.utils import db
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from shroud.slack.handlers.incoming_message import MessageEvent



def get_message_by_ts(ts: str, channel: str, client: WebClient) -> str:
    try:
        message = client.conversations_history(
            channel=channel, oldest=ts, inclusive=True, limit=1
        ).data["messages"][0]
        return message
    except IndexError:
        # This might be because it's a threaded message
        try:
            message = client.conversations_replies(
                channel=channel, ts=ts, oldest=ts, inclusive=True, limit=1).data["messages"][0]
            return message
        except IndexError:
            return None



def get_profile_picture_url(user_id, client: WebClient) -> str:
    user_info = client.users_info(user=user_id)
    profile_picture_url = user_info["user"]["profile"]["image_512"]
    return profile_picture_url


def get_name(user_id, client: WebClient) -> str:
    user_info = client.users_info(user=user_id)
    return user_info.data["user"]["real_name"]


def begin_forward(message: "MessageEvent", client: WebClient) -> str:
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
    selection_ts = selection_prompt.data["ts"]

    db.save_forward_start(
        dm_ts=message.ts,
        content=message.content,
        selection_ts=selection_ts,
        dm_channel=message.channel
    )

# def is_thread(event: Dict[str, Any]) -> bool:
#     return "thread_ts" in event
#     # return "thread_ts" in event or "thread_ts" in event.get("previous_message", {})

def apply_command_prefix(command: str) -> str:
    command = f"/{settings.app_name}-{command}"
    print(f"Adding command {command}")
    return command