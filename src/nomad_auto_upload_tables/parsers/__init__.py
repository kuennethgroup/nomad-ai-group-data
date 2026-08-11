import os
import re

from nomad.config.models.plugins import ParserEntryPoint
from pydantic import Field

# nomad.yaml is loaded by nomad-lab with plain `yaml.load(...)` - there is no
# shell-style environment variable substitution anywhere in NOMAD's config
# loading. A value like `api_key: '${MY_SECRET}'` in nomad.yaml (a very
# natural thing to write, since that syntax works in docker-compose.yaml) is
# therefore passed through completely literally, as the 'literal string
# "${MY_SECRET}"' - not the environment variable's value. Resolve that
# pattern ourselves so secrets can stay in the environment/.env file instead
# of nomad.yaml.
_ENV_VAR_PATTERN = re.compile(r'^\$\{(\w+)\}$')


def _resolve_env_placeholder(value: str | None) -> str | None:
    if not isinstance(value, str):
        return value
    match = _ENV_VAR_PATTERN.match(value.strip())
    if not match:
        return value
    return os.environ.get(match.group(1), value)


class TabularGuessParserEntryPoint(ParserEntryPoint):
    api_key: str | None = Field(
        default=None,
        description=(
            'API key for the OpenAI-compatible chat completions endpoint used to '
            'guess column semantics. Set this (and `model`) via nomad.yaml under '
            'plugins.entry_points.options to enable AI-assisted guessing; without '
            'it, the parser falls back to local heuristics. May be given as a '
            'literal value or as `${ENV_VAR_NAME}`, resolved against the process '
            'environment at load time (nomad.yaml itself does not do this).'
        ),
    )
    model: str | None = Field(
        default=None,
        description='Model name to request from the chat completions endpoint, e.g. "meta-llama-3.1-8b-instruct".',
    )
    base_url: str = Field(
        default='https://chat-ai.academiccloud.de/v1',
        description='Base URL of the OpenAI-compatible chat completions endpoint (default: GWDG SAIA).',
    )

    def load(self):
        from nomad_auto_upload_tables.parsers.tabular_guess import TabularGuessParser

        config = self.dict()
        for key in ('api_key', 'model', 'base_url'):
            config[key] = _resolve_env_placeholder(config.get(key))
        return TabularGuessParser(**config)


tabular_guess_parser = TabularGuessParserEntryPoint(
    name='TabularGuessParser',
    description=(
        'Matches uploaded .xlsx/.xls/.csv files and creates an entry with a '
        'guessed table schema for the user to review and correct. Column '
        'semantics are guessed by an AI chat completions endpoint if '
        '`api_key`/`model` are configured, otherwise by local heuristics.'
    ),
    mainfile_name_re=r'.*\.(xlsx|xls|csv)$',
)
