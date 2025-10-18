from pyairtable import Api, Table
from pyairtable.formulas import match
from shroud import settings
from slack_sdk import WebClient

table = None

# class RelayRecord(BaseModel):
#     dm_ts: Annotated[str, StringConstraints(pattern=r"^[0-9]{10}\.[0-9]{6}$")]
#     forwarded_ts: Annotated[str, StringConstraints(pattern=r"^[0-9]{10}\.[0-9]{6}$")] = None
#     selection_ts: Annotated[str, StringConstraints(pattern=r"^[0-9]{10}\.[0-9]{6}$")] = None
#     content: str = None
#     selection: str = None
#     dm_channel: str = None

def get_table() -> Table:
    api = Api(api_key=settings.airtable_token)
    table = api.table(settings.airtable_base_id, settings.airtable_table_name)
    return table


def clean_database(client: WebClient) -> None:
    """
    If either the DM or the forwarded message no longer exists, remove the record from the database
    """
    global table
    for list_of_records in table.iterate():
        for full_record in list_of_records:
            messages = []
            r = full_record["fields"]
            try:
                messages.extend(
                    [
                        m
                        for m in client.conversations_history(
                            channel=r["dm_channel"],
                            inclusive=True,
                            oldest=r["dm_ts"],
                            limit=1,
                        ).data["messages"]
                    ]
                )
                messages.extend(
                    [
                        m
                        for m in client.conversations_history(
                            channel=settings.channel,
                            inclusive=True,
                            oldest=r["forwarded_ts"],
                            limit=1,
                        ).data["messages"]
                    ]
                )
            except KeyError:
                table.delete(full_record["id"])
                continue
            
            if len(messages) < 2:
                table.delete(full_record["id"])

            for m in messages:
                if m.get("subtype") == "tombstone":
                    table.delete(full_record["id"])
                    break


def save_forward_start(content: str, dm_ts: str, selection_ts: str, dm_channel: str) -> None:
    global table
    table.create(
        {
            "dm_ts": dm_ts,
            "content": content,
            "selection_ts": selection_ts,
            "dm_channel": dm_channel,
        }
    )


def finish_forward(dm_ts, forwarded_ts) -> None:
    global table
    record = table.first(formula=match({"dm_ts": dm_ts}))
    if record is None:
        raise ValueError(f"Record with timestamp {dm_ts} not found")
    # Empty the selection so it's harder to figure out anonymous reports if a user sends an indentifiable message
    table.update(record["id"], {"forwarded_ts": forwarded_ts, "selection": None})


def save_selection(selection_ts, selection) -> None:
    global table
    record = table.first(formula=match({"selection_ts": selection_ts}))
    if record is None:
        raise ValueError(f"Record with timestamp {selection_ts} not found")
    
    table.update(record["id"], {"selection": selection})


def get_message_by_ts(ts) -> dict:
    global table
    # https://pyairtable.readthedocs.io/en/stable/tables.html#formulas
    # formula = OR(
    #     match({"forwarded_ts": ts}),
    #     match({"dm_ts": ts}),
    #     match({"selection_ts": ts})
    # )
    #
    # From the docs: "If match_any=True, expressions are grouped with OR(), record is return if any of the values match."
    formula = match(
        {"dm_ts": ts, "forwarded_ts": ts, "selection_ts": ts}, match_any=True
    )
    record = table.first(formula=formula)
    if record is None:
        return None
        # raise ValueError(f"Record with timestamp {ts} not found")
    return record




def main():
    global table
    table = get_table()


main()
