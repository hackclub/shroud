from dynaconf import Dynaconf, Validator
import re

settings = Dynaconf(
    envvar_prefix="SHROUD",
    load_dotenv=True,
    settings_files=["settings.toml", ".secrets.toml"],
    merge_enabled=True,
    environment=True,
)
settings.validators.register(
    validators=[
        Validator(
            "slack_bot_token",
            must_exist=True,
            condition=lambda x: x.startswith("xoxb-"),
            messages={"condition": "Must start with 'xoxb-'"},
        ),
        Validator(
            "slack_app_token",
            must_exist=True,
            condition=lambda x: x.startswith("xapp-"),
            messages={"condition": "Must start with 'xapp-'"},
        ),
        Validator(
            "channel",
            must_exist=True,
            condition=lambda x: re.match(r"^[CG][A-Z0-9]{10}$", x) is not None,
            messages={"condition": "Must look like C123ABC456 or G123ABC456"},
            default="C07JX2TK0UX",
        ),
        Validator(
            "airtable_token",
            default=None,
        ),
        Validator(
            "airtable_base_id",
            default=None,
        ),
        Validator(
            "airtable_table_name",
            default=None,
        ),
        Validator(
            "database_url",
            default="postgresql://postgres:postgres@localhost:5432/shroud",
        ),
        Validator(
            "airtable_fallback",
            default=True,
        ),
        Validator(
            "airtable_mirror",
            default=True,
        ),

        # Optional settings
        Validator(
            "trusted_auto_forward",
            default=[],
        ),
        Validator(
            "old_channel",
            default=None,
            condition=lambda x: x is None or re.match(r"^[CG][A-Z0-9]{10}$", x) is not None,
            messages={"condition": "Must look like C123ABC456 or G123ABC456"},
        ),
        Validator(
            "leading_help_text",
            default="",
        ),
        Validator(
            "app_name",
            default="shroud",
        ),
        Validator(
            "disable_anonymous",
            default=False,
        ),
    ],
)

settings.validators.validate()
