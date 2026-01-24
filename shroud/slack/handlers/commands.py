import yaml
import datetime
import importlib.resources
from pathlib import Path
from typing import Any, cast
from slack_sdk.web.client import WebClient
from slack_sdk.errors import SlackApiError
from slack_bolt.context.respond import Respond
from shroud.slack import app
from shroud.utils import db, utils
from shroud import settings

@app.command(utils.apply_command_prefix("clean-db"))
def clean_db(ack, respond: Respond, client: WebClient):
    print("Cleaning database")
    ack()
    db.clean_database(client)
    respond(
        "Removed any records where the DM or the forwarded message no longer exists."
    )
    print("Cleaned database")

@app.command(utils.apply_command_prefix("create-dm"))
def create_dm(ack, respond: Respond, client: WebClient, command):
    ack()
    allowlist_channel = settings.channel
    user_id = command["user_id"]
    target_user = command["text"].strip()

    # Check if user is in the allowlist channel
    try:
        resp = client.conversations_members(channel=allowlist_channel)
        data = cast(dict[str, Any], resp.data)
        members = cast(list[str], data.get("members", []))
        if user_id not in members:
            respond("You must be a member of the allowlist channel to use this command.")
            return
    except Exception as e:
        respond(f"Failed to verify channel membership: {e}")
        return

    # Extract the user ID from the format <@U1234|user>
    if target_user.startswith("<@") and "|" in target_user:
        target_user = target_user[2:].split("|")[0]
    else:
        respond("Unable to extract user ID.")
        return

    # Create a ~~DM~~ private channel with the target user and the person who ran the command
    try:
        invite_users = [user_id, target_user]
        channel_name= f"{settings.app_name}-{target_user.lower()}"
        create_resp = client.conversations_create(
            name=channel_name,
            is_private=True,
        )
        create_data = cast(dict[str, Any], create_resp.data)
        channel_data = cast(dict[str, Any], create_data.get("channel", {}))
        private_channel = str(channel_data.get("id", ""))
        existed = False
    except SlackApiError as e:
        if e.response["error"] == "name_taken":
            respond("A DM with this name already exists.")
        else:
            respond(f"Failed to create DM: {e}")
        # Get the channel ID from channel_name
        list_resp = client.conversations_list(types="private_channel")
        list_data = cast(dict[str, Any], list_resp.data)
        channels = cast(list[dict[str, Any]], list_data.get("channels", []))
        # next function retrieves the first matching channel from the generator.
        # If no match is found, it returns None.
        matched_channel = next(
            (channel for channel in channels if channel["name"] == channel_name),
            None,
        )
        if matched_channel is None:
            respond("Unable to find the private channel.")
            return
        private_channel = str(matched_channel["id"])
        existed = True
    else:
        respond(f"Created a prviate channel <#{private_channel}>")
    try:
        client.conversations_invite(
            channel=private_channel, users=",".join(invite_users)
        )
    except SlackApiError as e:
        if e.response["error"] == "already_in_channel":
            respond("You are already in this DM.")
        else:
            respond(f"Failed to invite users to the DM: {e}")
        # Send a message to the allowlist channel with a button to join the DM
        client.chat_postMessage(
            channel=allowlist_channel,
            text=f"A private channel has been created: <#{private_channel}> with <@{target_user}>. Click the button below to join.",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"A private channel has been created: <#{private_channel}> with <@{target_user}>. Click the button below to join.",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Join private channel",
                            },
                            "action_id": "join_private_channel",
                            "value": private_channel,
                        }
                    ],
                },
            ],
        )

@app.action("join_private_channel")
def join_dm(ack, body, client: WebClient):
    ack()
    user_id = body["user"]["id"]
    private_channel = body["actions"][0]["value"]

    try:
        # Invite the user to the DM channel
        client.conversations_invite(channel=private_channel, users=user_id)
        client.chat_postEphemeral(
            channel=private_channel,
            user=user_id,
            text="You have been added to the channel.",
        )
    except SlackApiError as e:
        if e.response["error"] == "already_in_channel":
            client.chat_postEphemeral(
                channel=private_channel,
                user=user_id,
                text="You are already in this DM.",
            )
        else:
            # Send an error message to the user
            client.chat_postEphemeral(
                channel=body["channel"]["id"],
                user=user_id,
                text=f"Failed to join channel: {e}",
            )

@app.command(utils.apply_command_prefix("unresolved"))
def unresolved_command(ack, respond: Respond, command):
    ack()
    
    # Parse optional days parameter (default 1)
    text = command.get("text", "").strip()
    try:
        days = float(text) if text else 1.0
        if days <= 0:
            days = 1.0
    except ValueError:
        respond("Invalid number. Usage: `/shroud-unresolved [days, default 1]`")
        return
    
    table = db.get_table()
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=days)
    cutoff_ts = str(cutoff.timestamp())
    
    # Filter: unresolved (empty resolve_time) and forwarded within timeframe
    formula = f"AND({{resolve_time}} = '', {{forwarded_ts}} != '', {{forwarded_ts}} >= '{cutoff_ts}')"
    records = table.all(formula=formula)
    
    unresolved: list[tuple[datetime.datetime, str, str]] = []
    for record in records:
        fields = record["fields"]
        forwarded_ts = fields.get("forwarded_ts")
        content = fields.get("content", "")
        if not content:
            label = "Thread"
        else:
            if len(content) <= 40:
                label = content
            else:
                truncated = content[:40]
                last_space = truncated.rfind(' ')
                if last_space == -1:
                    label = truncated + "..."
                else:
                    label = truncated[:last_space] + "..."
        if forwarded_ts:
            fwd_dt = datetime.datetime.fromtimestamp(float(forwarded_ts), tz=datetime.timezone.utc)
            unresolved.append((fwd_dt, forwarded_ts, label))
    
    # Format time period text, up to 72 hours then days
    if days <= 3:
        period_text = f"{round(days * 24)} hours"
    else:
        period_text = f"{round(days, 2):g} days"    
    if not unresolved:
        respond(f"No unresolved threads in the past {period_text}.")
        return
    
    unresolved.sort(key=lambda x: x[0], reverse=True)
    
    list_items = []
    for fwd_dt, forwarded_ts, label in unresolved:
        age = now - fwd_dt
        total_seconds = int(age.total_seconds())
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = remainder // 60
        if days > 0:
            age_str = f"{days}d {hours}h"
        elif hours > 0:
            age_str = f"{hours}h {minutes}m"
        elif minutes > 0:
            age_str = f"{minutes}m"
        
        link = f"https://hackclub.slack.com/archives/{settings.channel}/p{forwarded_ts.replace('.', '')}"
        list_items.append({
            "type": "rich_text_section",
            "elements": [
                {"type": "link", "url": link, "text": label},
                {"type": "text", "text": f" - {age_str} ago"}
            ]
        })
    
    blocks = [{
        "type": "rich_text",
        "elements": [
            {
                "type": "rich_text_section",
                "elements": [
                    {"type": "text", "text": f"Unresolved threads in the past {period_text} ({len(unresolved)})", "style": {"bold": True}},
                    {"type": "text", "text": "\n"}
                ]
            },
            {
                "type": "rich_text_list",
                "style": "bullet",
                "elements": list_items
            }
        ]
    }]
    
    respond(blocks=blocks)

@app.command(utils.apply_command_prefix("help"))
def help_command(ack, respond: Respond):
    ack()
    # The package looks like shroud.slack and we only want shroud/manifest.yml
    package_name = __package__.split(".")[0] if __package__ else "shroud"
    manifest_path = Path(str(importlib.resources.files(package_name))).parent / "manifest.yml"
    with open(manifest_path, "r") as f:
        features = yaml.safe_load(f)["features"]

    help_text = "Commands:" if not settings.leading_help_text else settings.leading_help_text + "\nCommands:"
    slash_commands = features.get("slash_commands", [])
    for command in slash_commands:
        try:
            help_text += f"\n`{command['command']} {command['usage_hint']}`: {command['description']}"
        except KeyError:
            # Most likely means that usage_hint is not defined
            help_text += f"\n`{command['command']}`: {command['description']}"
    if len(slash_commands) == 0:
        help_text += "\nNo commands available.\n"
    else:
        help_text += "\n"

    shortcuts = features.get("shortcuts", [])
    help_text += "\nShortcuts:"
    message_shortcuts_text = "Message shortcuts:"
    global_shortcuts_text = "Global shortcuts:"
    for shortcut in shortcuts:
        if shortcut["type"] == "message":
            message_shortcuts_text += (
                f"\n`{shortcut["name"]}`: {shortcut['description']}"
            )
        elif shortcut["type"] == "global":
            global_shortcuts_text += (
                f"\n`{shortcut["name"]}`: {shortcut['description']}"
            )
    if len(shortcuts) == 0:
        help_text += "\nNo shortcuts available."
    else:
        if message_shortcuts_text != "Message shortcuts:":
            help_text += f"\n{message_shortcuts_text}"
        if global_shortcuts_text != "Global shortcuts:":
            help_text += f"\n{global_shortcuts_text}"

    respond(help_text)