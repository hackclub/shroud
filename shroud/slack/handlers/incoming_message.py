from enum import Enum
from slack_bolt.context.say import Say
from slack_sdk import WebClient
from shroud import settings
from shroud.slack import app
from shroud.utils import db, utils
from slack_bolt.context.respond import Respond
from pydantic import BaseModel, StringConstraints, computed_field
from typing import Annotated, Any
import datetime



class ValidationRegexs(Enum):
    channel = r"^[CGD][A-Z0-9]{10}$"
    ts = r"^[0-9]{10}\.[0-9]{6}$"
    user = r"^U[A-Z0-9]{8,}$"


class MessageEvent(BaseModel):
    channel: Annotated[str, StringConstraints(pattern=ValidationRegexs.channel.value)]
    thread_ts: (
        Annotated[str, StringConstraints(pattern=ValidationRegexs.ts.value)] | None
    ) = None
    ts: Annotated[str, StringConstraints(pattern=ValidationRegexs.ts.value)]
    user: Annotated[str, StringConstraints(pattern=ValidationRegexs.user.value)]
    content: str = None
    content_post_update: str = None
    # Probably only needs to be for message_changed
    attachments: list[Any] = []

    class Subtypes(str, Enum):
        message_changed = "message_changed"
        file_share = "file_share"
        message_deleted = "message_deleted"
        normal = "normal"
        other = "other"

        @classmethod
        def _missing_(cls, value):
            if value is None:
                return cls.normal
            else:
                # raise ValueError(f"{value} is not a valid {cls.__name__}")
                # print("INFO: Received an event with subtype {value} that is not handled; ignoring it.")
                return cls.other

    subtype: Subtypes

    @computed_field
    @property
    def record(self) -> dict:
        fetched_result = db.get_message_by_ts(self.thread_ts or self.ts)
        return None if fetched_result is None else fetched_result

    class Target(BaseModel):
        channel: Annotated[
            str, StringConstraints(pattern=ValidationRegexs.channel.value)
        ]
        thread_ts: (
            Annotated[str, StringConstraints(pattern=ValidationRegexs.ts.value)] | None
        ) = None

    # class ForceReturn(Exception):
    #     """
    #     Error to be raised when the message event handling should be stopped as the event doesn't need to be handled
    #     """
    #     pass

    # Don't return_to_sender if outside a DM or confirmed relay
    return_to_sender: bool = False

    # def is_im(self, client: WebClient) -> bool:
    # return client.conversations_info(channel=self.channel).data["channel"]["is_im"]
    @computed_field
    @property
    def is_dm(self) -> bool:
        return self.channel.startswith("D")

    class PrefixInfo(BaseModel):
        should_forward: bool
        content_without_prefix: str

    @computed_field
    @property
    def get_prefix_info(self) -> PrefixInfo:
        content = self.content_post_update or self.content
        if content.startswith("?"):
            return self.PrefixInfo(
                should_forward=True,
                # Remove the '?' and since sometimes there's a space after it, remove that too (if it exists)
                # If it is an edited message, send the content with the edit statement otherwise remove the prefix and send it
                content_without_prefix=(content[2:] if content.startswith("? ") else content[1:]) if not self.content_post_update else self.content
            )
        return self.PrefixInfo(should_forward=False, content_without_prefix=content)

    # https://docs.pydantic.dev/2.3/usage/computed_fields/
    # @<function_name>.setter can also be used with a @computed_field with the same function name


# https://api.slack.com/events/message.im
@app.event("message")
def handle_message(event, say: Say, client: WebClient, respond: Respond, ack):
    # Acknowledge the event
    ack()

    # Depending on the subtype, pull out appropriate data and initialize the message model
    # https://api.slack.com/events/message#subtypes
    subtype = MessageEvent.Subtypes(event.get("subtype"))

    # Deleting a message in a relay results in a message_changed event with a differing reply_count and potentially a different latest_reply
    # In this case, the top-level message will always be a bot_message that shouldn't change so it's easy to just ignore it if a bot message is changed
    # If there's another random thread that's not a relay that has a reply deleted or edited it'll be ignored anyway since there is no record for that relay
    if event.get("message", {}).get("subtype") == "bot_message":
        print("INFO: Received a bot message or update; ignoring it.")
        return

    match subtype:
        case MessageEvent.Subtypes.file_share:
            message = MessageEvent(
                channel=event["channel"],
                thread_ts=event.get("thread_ts"),
                ts=event["ts"],
                user=event.get("user"),
                content=event.get("text", ""),
                subtype=subtype,
            )
            if message.record and message.is_dm:
                client.chat_postMessage(
                    channel=event["channel"],
                    thread_ts=event.get("thread_ts", event.get("ts")),
                    text="File uploads are not supported yet. Please re-send the message with the file uploaded to something like https://catbox.moe/ and then send the link in your message. This message was not forwarded.",
                )
            return
        case MessageEvent.Subtypes.normal:
            message = MessageEvent(
                channel=event["channel"],
                thread_ts=event.get("thread_ts"),
                ts=event["ts"],
                user=event.get("user"),
                content=event["text"],
                subtype=subtype,
            )
        case MessageEvent.Subtypes.message_changed:
            user = event["message"]["user"]
            original_text = event["previous_message"]["text"]
            new_text = event["message"]["text"]
            # https://api.slack.com/events/message/message_changed
            # to_send = f"<@{user}> updated a <{client.chat_getPermalink(channel=event['channel'], message_ts=event["message"]["ts"]).data["permalink"]}|message> to {event["message"]["text"]}"
            # Initally linked the message... before realizing the user probably wouldn't have access to the linked message. Embed it eventually?
            to_send = f"A message has been edited from ```{original_text}``` to ```{new_text}```"
            message = MessageEvent(
                channel=event["channel"],
                subtype=subtype,
                ts=event["message"]["ts"],
                content=to_send,
                content_post_update=new_text,
                user=user,
                thread_ts=event["message"].get("thread_ts"),
                attachments=event["message"].get("attachments", []),
            )
        case MessageEvent.Subtypes.message_deleted:
            message = MessageEvent(
                channel=event["channel"],
                subtype=subtype,
                ts=event["deleted_ts"],
                user=event["previous_message"]["user"],
                thread_ts=event["previous_message"].get("thread_ts"),
                return_to_sender=True,
                content="Message deletions are not forwarded.",
            )
        case MessageEvent.Subtypes.other:
            return

    if message.return_to_sender and (message.is_dm or message.record is not None):
        client.chat_postEphemeral(
            channel=message.channel,
            user=message.user,
            text=message.content,
        )
    elif (
        message.record is None
        and message.is_dm
        and message.subtype == MessageEvent.Subtypes.normal
    ):
        utils.begin_forward(message, client)
    elif message.record is not None and message.is_dm:
        client.chat_postMessage(
            channel=settings.channel,
            text=message.content,
            attachments=message.attachments,
            thread_ts=message.record["fields"]["forwarded_ts"],
        )
        # Add :white_check_mark: reaction to the DM message
        try:
            client.reactions_add(
                channel=message.channel,
                name="white_check_mark",
                timestamp=message.ts
            )
        except Exception as e:
            print(f"Failed to add checkmark reaction to DM message: {e}")
    elif message.record is not None and message.is_dm is False:
        if message.content.startswith("!"):
            client.chat_postEphemeral(
                channel=message.channel,
                thread_ts=message.ts,
                user=message.user,
                text="`!` does nothing. By default, messages are not forwarded unless `?` is prepended to them.",
            )
            return
        prefix_info = message.get_prefix_info
        if prefix_info.should_forward:
            client.chat_postMessage(
                channel=message.record["fields"]["dm_channel"],
                thread_ts=message.record["fields"]["dm_ts"],
                text=prefix_info.content_without_prefix,
                username=utils.get_name(message.user, client),
                icon_url=utils.get_profile_picture_url(message.user, client),
            )
            # Add :white_check_mark: reaction to the channel message
            try:
                client.reactions_add(
                    channel=message.channel,
                    name="white_check_mark",
                    timestamp=message.ts
                )
            except Exception as e:
                print(f"Failed to add checkmark reaction to channel message: {e}")
            if (
                not message.record["fields"].get("reply_time")
            ):
                # This is the first reply to the forwarded message
                forwarded_time = message.record["fields"].get("forwarded_ts")
                reply_time = message.ts
                try:
                    fwd_dt = datetime.datetime.fromtimestamp(float(forwarded_time), tz=datetime.timezone.utc)
                    reply_dt = datetime.datetime.fromtimestamp(float(reply_time), tz=datetime.timezone.utc)
                    time_diff = (reply_dt - fwd_dt).total_seconds()
                    formatted_time = str(datetime.timedelta(seconds=int(time_diff)))
                    db.get_table().update(message.record["id"], {"reply_time": formatted_time})
                except Exception as e:
                    print(f"Failed to record first reply time diff: {e}")
        else:
            print("INFO: received a message not prefixed with `!` or `?`; ignoring it.")
    else:
        print(
            "INFO: received an event that is not a DM and has no record; ignoring it."
        )