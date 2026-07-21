"""
AI-assisted column-semantics guessing, via any OpenAI-compatible chat
completions endpoint (e.g. GWDG's SAIA, https://chat-ai.academiccloud.de/v1,
or OpenAI itself). The endpoint, API key and model are all supplied by the
caller (see `parsers.tabular_guess.TabularGuessParserEntryPoint`) -- this
module has no notion of a "default" provider.

Kept free of any `nomad` import, like `guessing.py`, and used the same way:
on success it returns column guesses in the same shape `guessing.guess_columns`
expects via its `ai_guesses` argument; on any failure it returns `None` so the
caller can fall back to the local heuristics instead.
"""

from __future__ import annotations

import json
import re

import pandas as pd

from nomad_auto_upload_tables.guessing import (
    CATEGORIES,
    MAX_SAMPLE_VALUES,
    QUANTITY_TYPES,
    safe_confidence,
    safe_quantity_name,
    safe_unit,
)
from nomad_auto_upload_tables.schema_generation import PLOT_TYPES, normalize_material_formula

AI_PLOT_SUGGESTIONS_KEY = '__plot_suggestions__'
AI_MATERIAL_SUGGESTION_KEY = '__material_suggestion__'
AI_METHOD_SUGGESTION_KEY = '__method_suggestion__'

SYSTEM_PROMPT = (
    'You are a data analyst structuring a materials-science spreadsheet. '
    'You are given a JSON list of columns, each with its header text, pandas '
    'dtype, and a few example values. For each column, propose:\n'
    '- "guessed_name": a short snake_case quantity name\n'
    f'- "guessed_type": one of {QUANTITY_TYPES}\n'
    '- "guessed_unit": a pint-compatible unit string (e.g. "K", "Pa", "m/s"), '
    'or "" if the column has no physical unit\n'
    f'- "category": one of {CATEGORIES}\n'
    '- "confidence": your confidence in this guess, a number between 0 and 1\n'
    'You may also suggest useful plots and entry-level NOMAD results metadata. '
    'Respond with ONLY JSON, either the legacy array of column objects or an object '
    'with keys "columns", "plot_suggestions", "material_suggestion", and '
    '"method_suggestion". '
    f'Allowed plot types are {PLOT_TYPES}. Plot suggestions should contain '
    '"enabled_plots", "plot_label", and ordered "plot_columns" using the guessed '
    'quantity names. Material suggestions may contain "material_formula", '
    '"material_name", "structural_type", and "dimensionality". Method suggestions '
    'may contain "method_name" and "workflow_name". No prose, no markdown code fences.'
)

JSON_ARRAY_RE = re.compile(r'\[.*\]', re.DOTALL)


def _column_summary(df: pd.DataFrame) -> list[dict]:
    summary = []
    for header in df.columns:
        series = df[header]
        sample = series.dropna().unique()[:MAX_SAMPLE_VALUES]
        summary.append(
            {
                'header': str(header),
                'dtype': str(series.dtype),
                'sample_values': [str(v) for v in sample],
            }
        )
    return summary


def guess_with_ai(
    df: pd.DataFrame,
    api_key: str,
    model: str,
    base_url: str,
    logger=None,
) -> dict[str, dict] | None:
    """Ask the configured chat completions endpoint to guess each column's
    semantics. Returns a mapping from header to a guess dict (matching the
    keys `guessing.guess_columns` expects), or `None` if the request or its
    response could not be used."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': json.dumps(_column_summary(df))},
            ],
        )
        content = response.choices[0].message.content
    except Exception:
        if logger:
            logger.warning('AI column guessing request failed', exc_info=True)
        return None

    guesses = _parse_response(content, expected_headers=set(df.columns.astype(str)))
    if guesses is None and logger:
        logger.warning('AI column guessing returned an unusable response: %s', content)
    return guesses


def _parse_response(content: str, expected_headers: set[str]) -> dict[str, dict] | None:
    parsed = _load_json_response(content)
    if parsed is None:
        return None

    plot_suggestions = None
    material_suggestion = None
    method_suggestion = None
    if isinstance(parsed, dict):
        plot_suggestions = parsed.get('plot_suggestions') or parsed.get('plot_suggestion')
        material_suggestion = parsed.get('material_suggestion') or parsed.get('material')
        method_suggestion = parsed.get('method_suggestion') or parsed.get('method')
        parsed = parsed.get('columns') or parsed.get('column_guesses')
    if not isinstance(parsed, list):
        return None

    guesses = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        header = item.get('header')
        if header not in expected_headers:
            continue
        guessed_type = item.get('guessed_type')
        category = item.get('category')
        guesses[header] = {
            'guessed_name': safe_quantity_name(item.get('guessed_name'), fallback_header=header),
            'guessed_type': guessed_type if guessed_type in QUANTITY_TYPES else 'string',
            'guessed_unit': safe_unit(item.get('guessed_unit')),
            'category': category if category in CATEGORIES else 'other',
            'confidence': safe_confidence(item.get('confidence')),
        }

    if not guesses:
        return None

    cleaned_plot_suggestions = _clean_plot_suggestions(plot_suggestions)
    if cleaned_plot_suggestions:
        guesses[AI_PLOT_SUGGESTIONS_KEY] = cleaned_plot_suggestions
    cleaned_material_suggestion = _clean_material_suggestion(material_suggestion)
    if cleaned_material_suggestion:
        guesses[AI_MATERIAL_SUGGESTION_KEY] = cleaned_material_suggestion
    cleaned_method_suggestion = _clean_method_suggestion(method_suggestion)
    if cleaned_method_suggestion:
        guesses[AI_METHOD_SUGGESTION_KEY] = cleaned_method_suggestion
    return guesses


def _load_json_response(content: str):
    text = (content or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = JSON_ARRAY_RE.search(content or '')
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _clean_plot_suggestions(value) -> dict | None:
    if not isinstance(value, dict):
        return None

    raw_enabled = value.get('enabled_plots') or value.get('plot_types') or []
    if isinstance(raw_enabled, str):
        raw_enabled = [part.strip() for part in raw_enabled.split(',')]
    enabled_plots = []
    for plot_type in raw_enabled:
        plot_type = str(plot_type or '').strip()
        if plot_type in PLOT_TYPES and plot_type not in enabled_plots:
            enabled_plots.append(plot_type)

    raw_columns = value.get('plot_columns') or value.get('columns') or []
    if isinstance(raw_columns, str):
        raw_columns = [part.strip() for part in raw_columns.split(',')]
    plot_columns = []
    for column in raw_columns:
        clean = safe_quantity_name(column, fallback_header=str(column or ''))
        if clean and clean not in plot_columns:
            plot_columns.append(clean)

    plot_label = str(value.get('plot_label') or value.get('label') or '').strip()
    cleaned = {}
    if enabled_plots:
        cleaned['enabled_plots'] = enabled_plots
    if plot_label:
        cleaned['plot_label'] = plot_label
    if plot_columns:
        cleaned['plot_columns'] = plot_columns
    return cleaned or None


def _clean_material_suggestion(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    formula = normalize_material_formula(value.get('material_formula') or value.get('formula'))
    cleaned = {}
    if formula:
        cleaned['material_formula'] = formula
    material_name = str(value.get('material_name') or value.get('name') or '').strip()
    if material_name:
        cleaned['material_name'] = material_name
    structural_type = str(value.get('structural_type') or '').strip()
    if structural_type in {'bulk', 'surface', '2D', '1D', 'molecule', 'atom', 'unavailable'}:
        cleaned['structural_type'] = structural_type
    dimensionality = str(value.get('dimensionality') or '').strip()
    if dimensionality in {'0D', '1D', '2D', '3D', 'unavailable'}:
        cleaned['dimensionality'] = dimensionality
    return cleaned or None


def _clean_method_suggestion(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    cleaned = {}
    method_name = str(value.get('method_name') or value.get('name') or '').strip()
    workflow_name = str(value.get('workflow_name') or value.get('workflow') or '').strip()
    if method_name:
        cleaned['method_name'] = method_name
    if workflow_name:
        cleaned['workflow_name'] = workflow_name
    return cleaned or None


