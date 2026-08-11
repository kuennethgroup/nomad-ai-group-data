import os

from nomad_auto_upload_tables.parsers import TabularGuessParserEntryPoint


def test_env_placeholder_is_resolved_from_environment(monkeypatch):
    monkeypatch.setenv('MY_TEST_API_KEY', 'secret-value')
    entry_point = TabularGuessParserEntryPoint(
        name='TabularGuessParser',
        api_key='${MY_TEST_API_KEY}',
        model='some-model',
    )

    parser = entry_point.load()

    assert parser.api_key == 'secret-value'


def test_unresolvable_placeholder_is_left_as_is_and_literal_values_pass_through():
    os.environ.pop('MY_MISSING_API_KEY', None)
    entry_point = TabularGuessParserEntryPoint(
        name='TabularGuessParser',
        api_key='${MY_MISSING_API_KEY}',
        model='literal-model-name',
    )

    parser = entry_point.load()

    assert parser.api_key == '${MY_MISSING_API_KEY}'
    assert parser.model == 'literal-model-name'


def test_default_api_key_is_none():
    entry_point = TabularGuessParserEntryPoint(name='TabularGuessParser')

    parser = entry_point.load()

    assert parser.api_key is None
