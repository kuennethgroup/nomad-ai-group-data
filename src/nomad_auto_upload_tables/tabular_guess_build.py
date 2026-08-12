"""
Glue between the pure-pandas heuristics in :mod:`guessing` and the NOMAD
archive/metainfo objects defined in :mod:`schema_packages.tabular_guess`.

Kept as a separate top-level module (rather than living in either
``parsers`` or ``schema_packages``) so both can import it without a circular
import.
"""

from __future__ import annotations

import dataclasses
import math
import os
import re
from pathlib import PurePosixPath

import pandas as pd
import yaml

from nomad.utils import generate_entry_id

from nomad_auto_upload_tables.guessing import (
    ARCHIVE_CONTENT_MARKERS,
    QUANTITY_TYPES,
    coerce_value,
    guess_columns,
    is_supported_table_file,
    read_delimited_table,
    read_table,
)



def build_initial_guess(
    path: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    logger=None,
) -> tuple[str | None, int, list[dict], bool, dict | None]:
    """Read a spreadsheet on disk and return
    ``(sheet_name, n_rows, columns, ai_assisted, plot_suggestions)`` where ``columns`` is a list
    of dicts suitable for ``GuessedColumn(**d)``.

    If ``api_key`` and ``model`` are set, column semantics are guessed by an
    AI chat completions call (see ``ai_guessing.guess_with_ai``); on any
    failure (or if not configured) this falls back to the local heuristics in
    ``guessing.py``, and ``ai_assisted`` is ``False``.
    """
    df, sheet_name = read_table(path)

    ai_guesses = None
    plot_suggestions = None
    if api_key and model:
        from nomad_auto_upload_tables.ai_guessing import (
            AI_MATERIAL_SUGGESTION_KEY,
            AI_METHOD_SUGGESTION_KEY,
            AI_PLOT_SUGGESTIONS_KEY,
            guess_with_ai,
        )

        ai_guesses = guess_with_ai(df, api_key=api_key, model=model, base_url=base_url, logger=logger)
        if isinstance(ai_guesses, dict):
            ai_guesses = dict(ai_guesses)
            suggestions = {}
            if AI_PLOT_SUGGESTIONS_KEY in ai_guesses:
                suggestions.update(ai_guesses.pop(AI_PLOT_SUGGESTIONS_KEY))
            if AI_MATERIAL_SUGGESTION_KEY in ai_guesses:
                suggestions['material_suggestion'] = ai_guesses.pop(AI_MATERIAL_SUGGESTION_KEY)
            if AI_METHOD_SUGGESTION_KEY in ai_guesses:
                suggestions['method_suggestion'] = ai_guesses.pop(AI_METHOD_SUGGESTION_KEY)
            plot_suggestions = suggestions or None

    columns = [dataclasses.asdict(c) for c in guess_columns(df, ai_guesses=ai_guesses)]
    return sheet_name, len(df), columns, ai_guesses is not None, plot_suggestions


def _raise_if_archive_content(file_obj, data_file: str) -> None:
    position = file_obj.tell() if file_obj.seekable() else None
    sample = file_obj.read(4096)
    if position is not None:
        file_obj.seek(position)
    if isinstance(sample, bytes):
        sample = sample.decode('utf-8', errors='ignore')
    if any(marker in sample for marker in ARCHIVE_CONTENT_MARKERS):
        raise ValueError(f'File appears to be a NOMAD archive, not a source table: {data_file!r}')


def build_structured_rows(entry, archive) -> list:
    """Re-read ``entry``'s data file and build ``GuessedRow``/``GuessedProperty``
    instances from the (possibly user-corrected) column mapping in
    ``entry.columns``."""
    from nomad_auto_upload_tables.schema_packages.tabular_guess import (
        GuessedProperty,
        GuessedRow,
    )

    if not is_supported_table_file(entry.data_file):
        raise ValueError(f'Unsupported table file extension for {entry.data_file!r}')

    with archive.m_context.raw_file(entry.data_file) as f:
        if entry.data_file.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(f, sheet_name=entry.sheet_name or 0)
        else:
            _raise_if_archive_content(f, entry.data_file)
            df = read_delimited_table(f, filename=entry.data_file)

    included = [column for column in entry.columns if column.include is not False]
    rows = []
    for _, row in df.iterrows():
        properties = []
        for column in included:
            value = coerce_value(row[column.header], column.guessed_type)
            properties.append(
                GuessedProperty(
                    name=column.guessed_name,
                    value=value if value is None else str(value),
                    unit=column.guessed_unit or None,
                    category=column.category,
                )
            )
        rows.append(GuessedRow(properties=properties))
    return rows


def write_generated_artifacts(entry, archive, artifacts, *, logger=None) -> list[str]:
    """Write generated schema/entry YAML files and schedule them for processing.

    Existing files are left untouched unless ``entry.force_regenerate`` is true.
    Returns the list of files that were written or scheduled.
    """
    if getattr(artifacts, 'mapping_mode', 'column') == 'row':
        return _write_generated_row_artifacts(entry, archive, artifacts, logger=logger)

    context = archive.m_context
    schema_yaml, entry_yaml = _with_search_summary_quantities(
        entry, archive, artifacts.schema_yaml, artifacts.entry_yaml, artifacts, logger=logger
    )
    entry_yaml = _with_concrete_schema_reference(entry_yaml, artifacts, archive)
    files = [
        (artifacts.schema_file, schema_yaml),
        (artifacts.entry_file, entry_yaml),
    ]
    table_values_file = _build_table_values_file(entry, archive)
    if table_values_file:
        files.append(table_values_file)
    return _write_generated_files(
        context,
        files,
        force=getattr(entry, 'force_regenerate', False),
        logger=logger,
    )


def _write_generated_row_artifacts(entry, archive, artifacts, *, logger=None) -> list[str]:
    context = archive.m_context
    df = _read_source_table(entry, archive)
    schema_ref = _schema_m_def_ref(artifacts, archive)
    row_files = _row_entry_files(entry, df, artifacts, schema_ref)
    files = [(artifacts.schema_file, artifacts.schema_yaml), *row_files]
    included = [column for column in entry.columns if getattr(column, 'include', True) is not False]
    table_values_file = _table_values_file(entry, df, included)
    if table_values_file:
        files.append(table_values_file)
    return _write_generated_files(
        context,
        files,
        force=getattr(entry, 'force_regenerate', False),
        logger=logger,
    )


def _write_generated_files(context, files, *, force: bool, logger=None) -> list[str]:
    written: list[str] = []
    for path, content in files:
        if not path or not content:
            continue
        exists = hasattr(context, 'raw_path_exists') and context.raw_path_exists(path)
        if exists and not force:
            if logger:
                logger.info('Generated file already exists; not overwriting', path=path)
            continue
        _ensure_raw_parent_dir(context, path)
        with context.raw_file(path, 'w') as f:
            f.write(content)
        written.append(path)
        if hasattr(context, 'process_updated_raw_file'):
            context.process_updated_raw_file(path, allow_modify=True)
    return written


def _row_entry_files(entry, df: pd.DataFrame, artifacts, schema_ref: str) -> tuple[tuple[str, str], ...]:
    from nomad_auto_upload_tables.schema_generation import ROW_ENTRY_DIR, _base_name, _dump_yaml, _label_quantity, _quantity_name

    base = _base_name(entry.data_file or 'table')
    columns = [column for column in entry.columns if getattr(column, 'include', True) is not False]
    label_quantity = _label_quantity(columns)
    label_column = _row_label_column(columns, label_quantity)
    used_ids: set[str] = set()
    row_files: list[tuple[str, str]] = []
    for zero_index, (_, row) in enumerate(df.iterrows()):
        source_row = zero_index + 1
        row_id = _unique_row_id(_row_id(row, label_column, source_row), used_ids)
        data = {
            'm_def': schema_ref,
            'source_file': str(entry.data_file).strip().lstrip('/'),
            'source_row': source_row,
        }
        for column in columns:
            header = getattr(column, 'header', None)
            if header not in df.columns:
                continue
            value = _coerce_row_value(row[header], str(getattr(column, 'guessed_type', '') or 'string'))
            if value is None:
                continue
            data[_quantity_name(column)] = value
        payload = {'metadata': {'entry_name': row_id}, 'data': data}
        path = f'{ROW_ENTRY_DIR}/{base}/{row_id}.archive.yaml'
        row_files.append((path, _dump_yaml(payload)))
    return tuple(row_files)


def _schema_m_def_ref(artifacts, archive) -> str:
    upload_id = getattr(getattr(archive, 'metadata', None), 'upload_id', None)
    if upload_id:
        schema_entry_id = generate_entry_id(upload_id, artifacts.schema_file)
        return f'../uploads/{upload_id}/archive/{schema_entry_id}#/definitions/sections/{artifacts.section_name}'
    return f'../uploads/archive/mainfile/{artifacts.schema_file}#/definitions/sections/{artifacts.section_name}'


def _row_label_column(columns, label_quantity: str | None):
    from nomad_auto_upload_tables.schema_generation import _quantity_name

    preferred = [label_quantity, 'sample_id', 'sample_name', 'id', 'name']
    for preferred_name in preferred:
        if not preferred_name:
            continue
        for column in columns:
            if _quantity_name(column) == preferred_name:
                return column
    return None


def _row_id(row, label_column, source_row: int) -> str:
    if label_column is not None:
        header = getattr(label_column, 'header', None)
        if header in row.index:
            value = row[header]
            if not pd.isna(value) and str(value).strip():
                return _safe_row_id(str(value))
    return f'row_{source_row:04d}'


def _unique_row_id(row_id: str, used_ids: set[str]) -> str:
    candidate = row_id or 'row'
    index = 2
    while candidate in used_ids:
        candidate = f'{row_id}_{index}'
        index += 1
    used_ids.add(candidate)
    return candidate


def _safe_row_id(value: str) -> str:
    safe = re.sub(r'[^0-9A-Za-z_.-]+', '_', str(value).strip()).strip('._-')
    if not safe:
        safe = 'row'
    if safe in {'.', '..'}:
        safe = f'row_{safe.replace(".", "") or "entry"}'
    return PurePosixPath(safe).name


def _coerce_row_value(raw_value, guessed_type: str):
    if pd.isna(raw_value):
        return None
    guessed_type = guessed_type if guessed_type in QUANTITY_TYPES else 'string'
    try:
        if guessed_type == 'integer':
            value = pd.to_numeric(raw_value, errors='coerce')
            if pd.isna(value):
                return None
            return int(value)
        if guessed_type == 'float':
            value = pd.to_numeric(raw_value, errors='coerce')
            if pd.isna(value) or not math.isfinite(float(value)):
                return None
            return float(value)
        if guessed_type == 'boolean':
            if isinstance(raw_value, bool):
                return raw_value
            text = str(raw_value).strip().lower()
            if text in {'true', '1', 'yes', 'y'}:
                return True
            if text in {'false', '0', 'no', 'n'}:
                return False
            return None
        if guessed_type == 'datetime':
            value = pd.to_datetime(raw_value, errors='coerce')
            if pd.isna(value):
                return None
            return pd.Timestamp(value).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None
    text = str(raw_value).strip()
    return text or None



def _with_search_summary_quantities(entry, archive, schema_yaml: str, entry_yaml: str, artifacts, *, logger=None) -> tuple[str, str]:
    """Add scalar companion quantities that NOMAD can index for Explore widgets.

    NOMAD's dynamic search quantity indexing skips array quantities, while native
    tabular columns are arrays. These scalar summaries keep the table arrays as
    the source of truth and add conservative entry-level fields for search.
    """
    try:
        df = _read_source_table(entry, archive)
        summaries = _search_summaries(entry, df)
        if not summaries:
            return schema_yaml, entry_yaml

        schema_payload = yaml.safe_load(schema_yaml)
        entry_payload = yaml.safe_load(entry_yaml)
        section = schema_payload['definitions']['sections'][artifacts.section_name]
        quantities = section.setdefault('quantities', {})
        data = entry_payload.setdefault('data', {})

        for name, quantity, value in summaries:
            quantities[name] = quantity
            data[name] = value

        return (
            yaml.safe_dump(schema_payload, sort_keys=False, allow_unicode=True),
            yaml.safe_dump(entry_payload, sort_keys=False, allow_unicode=True),
        )
    except Exception as e:  # noqa: BLE001 - summaries are useful, but should never block generation
        if logger:
            logger.warning('Could not add searchable table summaries', exc_info=e)
        return schema_yaml, entry_yaml



def _read_source_table(entry, archive) -> pd.DataFrame:
    if not is_supported_table_file(entry.data_file):
        raise ValueError(f'Unsupported table file extension for {entry.data_file!r}')

    with archive.m_context.raw_file(entry.data_file) as f:
        if entry.data_file.lower().endswith(('.xlsx', '.xls')):
            return pd.read_excel(f, sheet_name=entry.sheet_name or 0)
        _raise_if_archive_content(f, entry.data_file)
        return read_delimited_table(f, filename=entry.data_file)


def _search_summaries(entry, df: pd.DataFrame) -> list[tuple[str, dict, object]]:
    from nomad_auto_upload_tables.schema_generation import _canonical_unit, _quantity_name, _yaml_type

    summaries: list[tuple[str, dict, object]] = []
    included = [column for column in entry.columns if getattr(column, 'include', True) is not False]
    used_names = {_quantity_name(column) for column in included}
    for column in included:
        header = getattr(column, 'header', None)
        if header not in df.columns:
            continue
        quantity_name = _quantity_name(column)
        guessed_type = str(getattr(column, 'guessed_type', '') or 'string')
        category = str(getattr(column, 'category', '') or '')
        unit = _canonical_unit(str(getattr(column, 'guessed_unit', '') or ''), quantity_name, category)
        series = df[header].dropna()
        if series.empty:
            continue

        if guessed_type in {'float', 'integer'}:
            numeric = pd.to_numeric(series, errors='coerce').dropna()
            if numeric.empty:
                continue
            for suffix, value in (
                ('mean', _clean_summary_float(numeric.mean())),
                ('min', _clean_summary_float(numeric.min())),
                ('max', _clean_summary_float(numeric.max())),
            ):
                if not math.isfinite(value):
                    continue
                name = _unique_search_name(f'{quantity_name}_{suffix}', used_names)
                quantity = _search_quantity_dict(
                    'np.float64',
                    f'Searchable {suffix} summary for imported column {header!r}.',
                    unit=unit,
                )
                summaries.append((name, quantity, value))
                used_names.add(name)
            continue

        unique_values = _unique_scalar_values(series, guessed_type)
        if len(unique_values) == 1:
            name = _unique_search_name(quantity_name, used_names)
            quantity = _search_quantity_dict(
                _yaml_type(guessed_type),
                f'Searchable single-value summary for imported column {header!r}.',
                unit=unit,
            )
            summaries.append((name, quantity, unique_values[0]))
            used_names.add(name)

    return summaries


def _build_table_values_file(entry, archive) -> tuple[str, str] | None:
    """Column-mode entry point: reads the source table itself, then delegates
    to `_table_values_file`. Row mode already has `df` on hand and calls
    `_table_values_file` directly instead (see `_write_generated_row_artifacts`)."""
    try:
        df = _read_source_table(entry, archive)
    except Exception:  # noqa: BLE001 - this companion entry is best-effort
        return None
    included = [column for column in entry.columns if getattr(column, 'include', True) is not False]
    return _table_values_file(entry, df, included)


def _table_values_file(entry, df: pd.DataFrame, columns) -> tuple[str, str] | None:
    """Build the (path, yaml) for a `TableValues` companion entry (see
    `schema_packages.table_values`): one `TableValue` per (row, column), in
    a fixed, plugin-schema quantity shape that's searchable and
    widget-bindable across every upload - unlike the per-upload generated
    schema `columns` are otherwise mapped into.

    Long format (one scalar-valued TableValue per row) rather than one
    array-valued TableValue per column: NOMAD only registers *scalar*
    quantities (shape == []) as dynamic search quantities usable in Explore
    dashboard widgets - an array-shaped quantity is invisible to them no
    matter how it's referenced (confirmed against
    nomad.metainfo.elasticsearch_extension.create_dynamic_quantity_annotation).
    """
    from nomad_auto_upload_tables.schema_generation import (
        TABLE_VALUES_DIR,
        _base_name,
        _canonical_unit,
        _dump_yaml,
        _quantity_name,
        _title_from_identifier,
    )

    base = _base_name(entry.data_file or 'table')
    column_specs = []
    for column in columns:
        header = getattr(column, 'header', None)
        if header not in df.columns:
            continue
        quantity_name = _quantity_name(column)
        guessed_type = str(getattr(column, 'guessed_type', '') or 'string')
        category = str(getattr(column, 'category', '') or '') or None
        unit = None
        if guessed_type in ('float', 'integer'):
            unit = _canonical_unit(str(getattr(column, 'guessed_unit', '') or ''), quantity_name, category or '') or None
        column_specs.append((header, quantity_name, guessed_type, category, unit))

    if not column_specs:
        return None

    values: list[dict] = []
    for zero_index, (_, row) in enumerate(df.iterrows()):
        source_row = zero_index + 1
        for header, quantity_name, guessed_type, category, unit in column_specs:
            raw_value = row[header]
            if pd.isna(raw_value):
                continue

            value: dict = {'property_name': quantity_name, 'source_row': source_row}
            if category:
                value['category'] = category

            if guessed_type in ('float', 'integer'):
                numeric = pd.to_numeric(raw_value, errors='coerce')
                if pd.isna(numeric):
                    continue
                value['numeric_value'] = _clean_summary_float(numeric)
                if unit:
                    value['unit'] = unit
            else:
                value['string_value'] = str(raw_value)

            values.append(value)

    if not values:
        return None

    payload = {
        'data': {
            'm_def': 'nomad_auto_upload_tables.schema_packages.table_values.TableValues',
            'name': f'{_title_from_identifier(base)} values',
            'source_file': str(entry.data_file or '').strip().lstrip('/'),
            'values': values,
        }
    }
    path = f'{TABLE_VALUES_DIR}/{base}_values.archive.yaml'
    return path, _dump_yaml(payload)


def _clean_summary_float(value) -> float:
    return float(f'{float(value):.12g}')

def _search_quantity_dict(quantity_type: str, description: str, *, unit: str = '') -> dict:
    quantity = {
        'type': quantity_type,
        'description': description,
        'm_annotations': {'display': {'visible': False}},
    }
    if unit:
        quantity['unit'] = unit
    return quantity


def _unique_search_name(name: str, used_names: set[str]) -> str:
    candidate = name
    index = 2
    while candidate in used_names:
        candidate = f'{name}_{index}'
        index += 1
    return candidate


def _unique_scalar_values(series: pd.Series, guessed_type: str) -> list[object]:
    values: list[object] = []
    for raw in series:
        value = coerce_value(raw, guessed_type)
        if value is None:
            continue
        if guessed_type == 'boolean':
            value = bool(value)
        else:
            value = str(value)
        if value not in values:
            values.append(value)
        if len(values) > 1:
            break
    return values

def _with_concrete_schema_reference(entry_yaml: str, artifacts, archive) -> str:
    upload_id = getattr(getattr(archive, 'metadata', None), 'upload_id', None)
    if not upload_id:
        return entry_yaml

    try:
        payload = yaml.safe_load(entry_yaml)
        data = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return entry_yaml
        schema_entry_id = generate_entry_id(upload_id, artifacts.schema_file)
        data['m_def'] = (
            f'../uploads/{upload_id}/archive/{schema_entry_id}'
            f'#/definitions/sections/{artifacts.section_name}'
        )
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    except Exception:  # noqa: BLE001 - fall back to the generic URL and let NOMAD report errors
        return entry_yaml

def _ensure_raw_parent_dir(context, path: str) -> None:
    dirname = os.path.dirname(path)
    if not dirname or not hasattr(context, 'raw_path'):
        return
    os.makedirs(os.path.join(context.raw_path(), dirname), exist_ok=True)
