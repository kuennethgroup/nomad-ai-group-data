"""
Heuristics for guessing a column-level schema from a pandas DataFrame.

This module is intentionally free of any ``nomad`` import so it can be used
and unit-tested on its own (e.g. from a plain script handed a DataFrame),
and reused unchanged by the NOMAD parser/normalizer that wrap it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import pandas as pd
import pandas.api.types as ptypes

UNIT_PATTERN = re.compile(r'[\(\[]([^()\[\]]+)[\)\]]\s*$')

# Keyword -> ontology category used to guess the semantic meaning of a column
# from its header text. Order matters: first match wins, so more specific
# keywords should come before more generic ones.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    'sample_id': ['sample id', 'sample_id', 'specimen', 'sample name', 'sample'],
    'composition': ['composition', 'formula', 'stoichiometry', 'at%', 'wt%'],
    'concentration': ['concentration', 'molarity', 'conc.', 'conc'],
    'temperature': ['temperature', 'temp.', 'temp'],
    'pressure': ['pressure'],
    'time': ['duration', 'timestamp', 'date', 'time'],
    'mass': ['mass', 'weight'],
    'length': ['thickness', 'diameter', 'length', 'width', 'height'],
    'voltage': ['voltage', 'potential'],
    'current': ['current'],
    'frequency': ['frequency', 'freq'],
    'energy': ['enthalpy', 'energy'],
    'process_parameter': ['rate', 'speed', 'power', 'flow'],
    'measurement_result': ['result', 'measurement', 'intensity', 'signal', 'value'],
}

CATEGORIES = [*CATEGORY_KEYWORDS.keys(), 'other']

QUANTITY_TYPES = ['string', 'integer', 'float', 'boolean', 'datetime']

KNOWN_KEYWORD_CONFIDENCE = 0.8
DEFAULT_CONFIDENCE = 0.2
MAX_SAMPLE_VALUES = 5
SUPPORTED_TABLE_EXTENSIONS = ('.csv', '.tsv', '.xlsx', '.xls')
ARCHIVE_CONTENT_MARKERS = ('"m_def"', '"data"', '"archive"', '"metadata"')


@dataclass
class ColumnGuess:
    header: str
    guessed_name: str
    guessed_type: str
    guessed_unit: str
    category: str
    confidence: float
    n_rows: int
    n_missing: int
    sample_values: str


def read_table(path: str, sheet_name: int | str = 0) -> tuple[pd.DataFrame, str | None]:
    """Read an Excel or CSV file at ``path`` into a DataFrame.

    Returns the DataFrame and the sheet name that was used (``None`` for CSV).
    """
    lower = str(path).lower()
    if lower.endswith(('.xlsx', '.xls')):
        df = pd.read_excel(path, sheet_name=sheet_name)
        used_sheet = sheet_name if isinstance(sheet_name, str) else _first_sheet_name(path)
        return df, used_sheet
    if lower.endswith(('.csv', '.tsv')):
        if is_likely_nomad_archive_file(path):
            raise ValueError(f'File appears to be a NOMAD archive, not a source table: {path!r}')
        return read_delimited_table(path, filename=lower), None
    raise ValueError(f'Unsupported table file extension for {path!r}')


def is_supported_table_file(path: str) -> bool:
    return str(path).lower().endswith(SUPPORTED_TABLE_EXTENSIONS)


def read_delimited_table(file_or_path, *, filename: str | None = None) -> pd.DataFrame:
    """Read CSV-like table files with conservative delimiter handling.

    ``sep=None`` lets pandas use Python's CSV sniffer for comma and semicolon
    CSV files. TSV files are explicit because tabs are unambiguous and common
    enough to avoid relying on sniffing.
    """
    lower = str(filename or file_or_path).lower()
    if lower.endswith('.tsv'):
        return pd.read_csv(file_or_path, sep='\t')
    return pd.read_csv(file_or_path, sep=None, engine='python')


def is_likely_nomad_archive_file(path: str) -> bool:
    """Return ``True`` for serialized NOMAD archive files.

    This intentionally looks at content, not just the extension. During save or
    reprocessing, generated archive content can be handed around with names
    that are not trustworthy enough to pass directly to pandas.
    """
    lower = str(path).lower()
    if lower.endswith(('.archive.json', '.archive.yaml', '.archive.yml')):
        return True
    try:
        with open(path, 'rb') as f:
            sample = f.read(4096)
    except OSError:
        return False

    stripped = sample.lstrip()
    if not stripped.startswith((b'{', b'[')):
        return False
    text = stripped[:1024].decode('utf-8', errors='ignore')
    return any(marker in text for marker in ARCHIVE_CONTENT_MARKERS)


def _first_sheet_name(path: str) -> str:
    with pd.ExcelFile(path) as xls:
        return xls.sheet_names[0]


def guess_unit(header: str) -> str | None:
    """Pull a pint-parseable unit out of a header like ``'Temperature (K)'``."""
    match = UNIT_PATTERN.search(header)
    if not match:
        return None
    candidate = match.group(1).strip()
    try:
        from pint import UnitRegistry

        UnitRegistry()(candidate)
    except Exception:
        return None
    return candidate


def guess_category(header: str) -> tuple[str, float]:
    lower = header.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            return category, KNOWN_KEYWORD_CONFIDENCE
    return 'other', DEFAULT_CONFIDENCE


def guess_type(series: pd.Series) -> str:
    if ptypes.is_bool_dtype(series):
        return 'boolean'
    if ptypes.is_integer_dtype(series):
        return 'integer'
    if ptypes.is_float_dtype(series):
        return 'float'
    if ptypes.is_datetime64_any_dtype(series):
        return 'datetime'
    non_null = series.dropna()
    if not non_null.empty and pd.to_datetime(non_null, errors='coerce', format='mixed').notna().all():
        return 'datetime'
    return 'string'


def clean_name(header: str) -> str:
    """Turn a free-text header into a snake_case identifier, unit suffix stripped."""
    without_unit = UNIT_PATTERN.sub('', header).strip()
    name = re.sub(r'[^0-9a-zA-Z]+', '_', without_unit).strip('_').lower()
    return name or 'column'


def safe_quantity_name(value, *, fallback_header: str) -> str:
    name = clean_name(str(value or fallback_header))
    if name[0].isdigit():
        name = f'column_{name}'
    return name


def safe_unit(value) -> str:
    unit = str(value or '').strip()
    if not unit:
        return ''
    try:
        from pint import UnitRegistry

        UnitRegistry()(unit)
    except Exception:
        return ''
    return unit


def safe_confidence(value) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(confidence):
        return 0.5
    return min(1.0, max(0.0, confidence))


def guess_columns(
    df: pd.DataFrame, ai_guesses: dict[str, dict] | None = None
) -> list[ColumnGuess]:
    """Build a `ColumnGuess` per column of `df`.

    For columns present in `ai_guesses` (see `ai_guessing.guess_with_ai`), the
    AI-proposed name/type/unit/category/confidence are used instead of the
    local heuristics below.
    """
    columns = []
    for header in df.columns:
        header_str = str(header)
        series = df[header]
        ai_guess = (ai_guesses or {}).get(header_str)
        if ai_guess:
            guessed_name = safe_quantity_name(ai_guess.get('guessed_name'), fallback_header=header_str)
            guessed_type = ai_guess.get('guessed_type')
            guessed_type = guessed_type if guessed_type in QUANTITY_TYPES else 'string'
            guessed_unit = safe_unit(ai_guess.get('guessed_unit'))
            category = ai_guess.get('category')
            category = category if category in CATEGORIES else 'other'
            confidence = safe_confidence(ai_guess.get('confidence'))
        else:
            category, confidence = guess_category(header_str)
            guessed_name = clean_name(header_str)
            guessed_type = guess_type(series)
            guessed_unit = guess_unit(header_str) or ''
        sample = ', '.join(str(v) for v in series.dropna().unique()[:MAX_SAMPLE_VALUES])
        columns.append(
            ColumnGuess(
                header=header_str,
                guessed_name=guessed_name,
                guessed_type=guessed_type,
                guessed_unit=guessed_unit,
                category=category,
                confidence=confidence,
                n_rows=int(series.notna().sum()),
                n_missing=int(series.isna().sum()),
                sample_values=sample,
            )
        )
    return columns


def coerce_value(raw_value, guessed_type: str):
    if pd.isna(raw_value):
        return None
    try:
        if guessed_type == 'integer':
            return int(raw_value)
        if guessed_type == 'float':
            return float(raw_value)
        if guessed_type == 'boolean':
            return bool(raw_value)
        if guessed_type == 'datetime':
            return pd.Timestamp(raw_value).isoformat()
    except (TypeError, ValueError):
        pass
    return str(raw_value)
