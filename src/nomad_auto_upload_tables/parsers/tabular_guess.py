import json
import os

from nomad.parsing import MatchingParser

from nomad_auto_upload_tables.guessing import is_likely_nomad_archive_file, is_supported_table_file
from nomad_auto_upload_tables.schema_generation import dump_review_yaml, generated_review_file
from nomad_auto_upload_tables.schema_packages.tabular_guess import (
    GuessedColumn,
    GuessedProperty,
    GuessedRow,
    TabularGuess,
)
from nomad_auto_upload_tables.tabular_guess_build import build_initial_guess, write_generated_artifacts
from nomad_auto_upload_tables.schema_generation import build_generated_artifacts


class TabularGuessParser(MatchingParser):
    """Matches uploaded source tables and creates a separate schema-review entry.

    CSV/XLSX mainfiles remain visible source data. The parser writes a generated
    review archive that instantiates :class:`TabularGuess`; only that review entry
    can generate native NOMAD schema/data archive files after user confirmation.
    """

    def __init__(self, *, api_key=None, model=None, base_url=None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def after_normalization(self, archive, logger=None):
        if isinstance(archive.data, TabularGuess):
            _generate_confirmed_artifacts(archive.data, archive, logger=logger)

    def parse(self, mainfile, archive, logger=None, child_archives=None):
        if isinstance(archive.data, TabularGuess):
            return
        if not is_supported_table_file(mainfile):
            if _restore_tabular_guess_archive(mainfile, archive, logger=logger):
                return
            if logger:
                logger.warning('Skipping unsupported table file: %s', mainfile)
            return

        if is_likely_nomad_archive_file(mainfile):
            if _restore_tabular_guess_archive(mainfile, archive, logger=logger):
                return
            if logger:
                logger.warning('Skipping archive-like file that is not a source table: %s', mainfile)
            return

        data_file = archive.metadata.mainfile if archive.metadata else mainfile.rsplit('/', 1)[-1]
        try:
            sheet_name, n_rows, columns, ai_assisted, plot_suggestions = build_initial_guess(
                mainfile,
                api_key=self.api_key,
                model=self.model,
                base_url=self.base_url,
                logger=logger,
            )
        except ValueError as e:
            if logger:
                logger.warning('Skipping file that is not a source table: %s', e)
            return

        review_yaml = dump_review_yaml(
            data_file=data_file,
            sheet_name=sheet_name,
            n_rows=n_rows,
            columns=columns,
            ai_assisted=ai_assisted,
            plot_suggestions=plot_suggestions,
        )
        review_file = generated_review_file(data_file)
        if _write_generated_raw_file(archive, review_file, review_yaml, allow_existing=True, logger=logger):
            return

        # Fallback for simple unit-test contexts without writable NOMAD raw storage.
        archive.data = TabularGuess(
            data_file=data_file,
            sheet_name=sheet_name,
            n_rows=n_rows,
            ai_assisted=ai_assisted,
            columns=[GuessedColumn(**column) for column in columns],
        )


def _generate_confirmed_artifacts(entry: TabularGuess, archive, *, logger=None) -> bool:
    if not (entry.confirm_schema and entry.columns and entry.data_file):
        return False
    if entry.mapping_mode not in (None, 'column'):
        if logger:
            logger.warning('Only column mapping mode is supported for generated schemas in this implementation')
        return False
    try:
        artifacts = build_generated_artifacts(entry)
        write_generated_artifacts(entry, archive, artifacts, logger=logger)
    except Exception as e:  # noqa: BLE001
        if logger:
            logger.error('Failed to generate NOMAD schema and entry from confirmed tabular review', exc_info=e)
        return False
    return True


def _write_generated_raw_file(archive, path: str, content: str, *, allow_existing: bool, logger=None) -> bool:
    context = getattr(archive, 'm_context', None)
    if context is None or not hasattr(context, 'raw_file'):
        return False
    try:
        exists = hasattr(context, 'raw_path_exists') and context.raw_path_exists(path)
        if exists and allow_existing:
            if hasattr(context, 'process_updated_raw_file'):
                context.process_updated_raw_file(path, allow_modify=True)
            return True
        _ensure_raw_parent_dir(context, path)
        with context.raw_file(path, 'w') as f:
            f.write(content)
        if hasattr(context, 'process_updated_raw_file'):
            context.process_updated_raw_file(path, allow_modify=True)
    except Exception as e:  # noqa: BLE001
        if logger:
            logger.warning('Could not write generated review archive %s: %s', path, e)
        return False
    return True


def _ensure_raw_parent_dir(context, path: str) -> None:
    dirname = os.path.dirname(path)
    if not dirname or not hasattr(context, 'raw_path'):
        return
    os.makedirs(os.path.join(context.raw_path(), dirname), exist_ok=True)


def _restore_tabular_guess_archive(mainfile, archive, *, logger=None) -> bool:
    """Restore ``archive.data`` from serialized NOMAD archive content."""
    try:
        with open(mainfile, encoding='utf-8') as f:
            payload = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False

    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not _is_tabular_guess_data(data):
        return False

    try:
        archive.data = _tabular_guess_from_dict(data)
    except Exception as e:  # noqa: BLE001 - keep parser defensive during reprocessing
        if logger:
            logger.warning('Could not restore TabularGuess archive data from %s: %s', mainfile, e)
        return False
    return True


def _is_tabular_guess_data(data: dict) -> bool:
    m_def = str(data.get('m_def', ''))
    return m_def.endswith('schema_packages.tabular_guess.TabularGuess') or m_def.endswith('.TabularGuess')


def _tabular_guess_from_dict(data: dict) -> TabularGuess:
    columns = [
        GuessedColumn(**_without_metainfo_keys(column))
        for column in data.get('columns', [])
        if isinstance(column, dict)
    ]
    rows = [
        GuessedRow(
            properties=[
                GuessedProperty(**_without_metainfo_keys(prop))
                for prop in row.get('properties', [])
                if isinstance(prop, dict)
            ]
        )
        for row in data.get('rows', [])
        if isinstance(row, dict)
    ]
    return TabularGuess(
        data_file=data.get('data_file'),
        sheet_name=data.get('sheet_name'),
        n_rows=data.get('n_rows'),
        ai_assisted=data.get('ai_assisted', False),
        confirm_schema=data.get('confirm_schema', False),
        force_regenerate=data.get('force_regenerate', False),
        generated_section_name=data.get('generated_section_name'),
        generated_schema_file=data.get('generated_schema_file'),
        generated_entry_file=data.get('generated_entry_file'),
        mapping_mode=data.get('mapping_mode', 'column'),
        enable_xy_scatter=data.get('enable_xy_scatter', bool(data.get('suggested_plot_x') and data.get('suggested_plot_y'))),
        enable_xy_line=data.get('enable_xy_line', False),
        enable_area=data.get('enable_area', False),
        enable_bar=data.get('enable_bar', False),
        enable_histogram=data.get('enable_histogram', False),
        enable_box=data.get('enable_box', False),
        enable_violin=data.get('enable_violin', False),
        enable_heatmap=data.get('enable_heatmap', False),
        enable_scatter_3d=data.get('enable_scatter_3d', False),
        enable_colored_scatter=data.get('enable_colored_scatter', False),
        plot_label=data.get('plot_label'),
        plot_columns=data.get('plot_columns')
        or ', '.join(value for value in (data.get('suggested_plot_x'), data.get('suggested_plot_y')) if value),
        columns=columns,
        rows=rows,
    )


def _without_metainfo_keys(values: dict) -> dict:
    return {key: value for key, value in values.items() if not key.startswith('m_')}
