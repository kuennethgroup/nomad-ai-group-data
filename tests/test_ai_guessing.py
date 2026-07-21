import json

import pandas as pd

from nomad_auto_upload_tables.ai_guessing import _parse_response, guess_with_ai

DF = pd.DataFrame(
    {
        'Sample ID': ['S001', 'S002'],
        'Temperature (K)': [300.5, 310.2],
    }
)

VALID_RESPONSE = json.dumps(
    [
        {
            'header': 'Sample ID',
            'guessed_name': 'sample_identifier',
            'guessed_type': 'string',
            'guessed_unit': '',
            'category': 'sample_id',
            'confidence': 0.95,
        },
        {
            'header': 'Temperature (K)',
            'guessed_name': 'temperature',
            'guessed_type': 'float',
            'guessed_unit': 'K',
            'category': 'temperature',
            'confidence': 0.9,
        },
    ]
)


def test_parse_response_extracts_valid_json_array():
    guesses = _parse_response(VALID_RESPONSE, expected_headers={'Sample ID', 'Temperature (K)'})
    assert guesses['Temperature (K)']['guessed_unit'] == 'K'
    assert guesses['Temperature (K)']['category'] == 'temperature'
    assert guesses['Sample ID']['guessed_name'] == 'sample_identifier'


def test_parse_response_extracts_optional_plot_suggestions():
    response = json.dumps(
        {
            'columns': json.loads(VALID_RESPONSE),
            'plot_suggestions': {
                'enabled_plots': ['xy_scatter', 'colored_scatter', 'parallel_coordinates', 'bad_plot'],
                'plot_label': 'AI overview',
                'plot_columns': ['temperature', 'sample identifier'],
            },
        }
    )

    guesses = _parse_response(response, expected_headers={'Sample ID', 'Temperature (K)'})

    assert guesses['__plot_suggestions__'] == {
        'enabled_plots': ['xy_scatter', 'colored_scatter'],
        'plot_label': 'AI overview',
        'plot_columns': ['temperature', 'sample_identifier'],
    }


def test_parse_response_extracts_optional_material_and_method_suggestions():
    response = json.dumps(
        {
            'columns': json.loads(VALID_RESPONSE),
            'material_suggestion': {
                'material_formula': 'K2Zn2BiSe4',
                'material_name': 'Test material',
                'structural_type': 'bulk',
                'dimensionality': '3D',
            },
            'method_suggestion': {
                'method_name': 'XRD',
                'workflow_name': 'Tabular import',
            },
        }
    )

    guesses = _parse_response(response, expected_headers={'Sample ID', 'Temperature (K)'})

    assert guesses['__material_suggestion__'] == {
        'material_formula': 'K2Zn2BiSe4',
        'material_name': 'Test material',
        'structural_type': 'bulk',
        'dimensionality': '3D',
    }
    assert guesses['__method_suggestion__'] == {
        'method_name': 'XRD',
        'workflow_name': 'Tabular import',
    }


def test_parse_response_extracts_formula_from_material_label():
    response = json.dumps(
        {
            'columns': json.loads(VALID_RESPONSE),
            'material_suggestion': {
                'material_formula': 'al2o3_based',
                'material_name': 'Alumina based sample',
            },
        }
    )

    guesses = _parse_response(response, expected_headers={'Sample ID', 'Temperature (K)'})

    assert guesses['__material_suggestion__'] == {
        'material_formula': 'Al2O3',
        'material_name': 'Alumina based sample',
    }


def test_parse_response_ignores_invalid_material_suggestion_parts():
    response = json.dumps(
        {
            'columns': json.loads(VALID_RESPONSE),
            'material_suggestion': {
                'material_formula': 'not a formula',
                'structural_type': 'crystalline-ish',
                'dimensionality': '4D',
            },
            'method_suggestion': {'method_name': ''},
        }
    )

    guesses = _parse_response(response, expected_headers={'Sample ID', 'Temperature (K)'})

    assert '__material_suggestion__' not in guesses
    assert '__method_suggestion__' not in guesses

def test_parse_response_strips_markdown_code_fences():
    fenced = f'```json\n{VALID_RESPONSE}\n```'
    guesses = _parse_response(fenced, expected_headers={'Sample ID', 'Temperature (K)'})
    assert guesses is not None
    assert set(guesses) == {'Sample ID', 'Temperature (K)'}


def test_parse_response_ignores_unexpected_headers():
    guesses = _parse_response(VALID_RESPONSE, expected_headers={'Sample ID'})
    assert set(guesses) == {'Sample ID'}


def test_parse_response_rejects_invalid_type_and_category():
    response = json.dumps(
        [
            {
                'header': 'Sample ID',
                'guessed_name': 'x',
                'guessed_type': 'not-a-real-type',
                'guessed_unit': '',
                'category': 'not-a-real-category',
                'confidence': 'not-a-number',
            }
        ]
    )
    guesses = _parse_response(response, expected_headers={'Sample ID'})
    assert guesses['Sample ID']['guessed_type'] == 'string'
    assert guesses['Sample ID']['category'] == 'other'
    assert guesses['Sample ID']['confidence'] == 0.5


def test_parse_response_sanitizes_ai_values_that_could_break_archives():
    response = json.dumps(
        [
            {
                'header': 'Sample ID',
                'guessed_name': '../Bad Name {m_def}',
                'guessed_type': 'integer',
                'guessed_unit': 'not a unit at all',
                'category': 'sample_id',
                'confidence': 99,
            },
            {
                'header': 'Temperature (K)',
                'guessed_name': '123 temperature',
                'guessed_type': 'float',
                'guessed_unit': 'K',
                'category': 'temperature',
                'confidence': '-inf',
            },
            {
                'header': 'not in the dataframe',
                'guessed_name': 'ignored',
                'guessed_type': 'string',
                'guessed_unit': '',
                'category': 'other',
                'confidence': 0.5,
            },
        ]
    )

    guesses = _parse_response(response, expected_headers={'Sample ID', 'Temperature (K)'})

    assert set(guesses) == {'Sample ID', 'Temperature (K)'}
    assert guesses['Sample ID']['guessed_name'] == 'bad_name_m_def'
    assert guesses['Sample ID']['guessed_unit'] == ''
    assert guesses['Sample ID']['confidence'] == 1.0
    assert guesses['Temperature (K)']['guessed_name'] == 'column_123_temperature'
    assert guesses['Temperature (K)']['guessed_unit'] == 'K'
    assert guesses['Temperature (K)']['confidence'] == 0.5


def test_parse_response_returns_none_for_garbage():
    assert _parse_response('not json at all', expected_headers={'Sample ID'}) is None
    assert _parse_response('', expected_headers={'Sample ID'}) is None


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        return type('Resp', (), {'choices': [_FakeChoice(self._content)]})()


class _FakeChat:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)


class FakeOpenAI:
    """Stands in for `openai.OpenAI`, returning a fixed chat completion."""

    response_content = VALID_RESPONSE

    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key
        self.base_url = base_url
        self.chat = _FakeChat(self.response_content)


def test_guess_with_ai_returns_parsed_guesses(monkeypatch):
    monkeypatch.setattr('openai.OpenAI', FakeOpenAI)
    guesses = guess_with_ai(DF, api_key='sk-test', model='some-model', base_url='https://example.invalid/v1')
    assert guesses['Temperature (K)']['category'] == 'temperature'


def test_guess_with_ai_returns_none_on_request_failure(monkeypatch):
    class RaisingOpenAI:
        def __init__(self, **kwargs):
            raise RuntimeError('network is down')

    monkeypatch.setattr('openai.OpenAI', RaisingOpenAI)
    assert guess_with_ai(DF, api_key='sk-test', model='some-model', base_url='https://example.invalid/v1') is None
