from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml

from nomad_auto_upload_tables.guessing import safe_quantity_name, safe_unit

SCHEMA_DIR = 'generated_schemas'
ENTRY_DIR = 'generated_entries'
ROW_ENTRY_DIR = 'generated_row_entries'
REVIEW_DIR = 'generated_reviews'

# Every generated entry (column mode and row mode) inherits ElnBaseSection and
# carries this fixed tag, which ElnBaseSection.normalize() copies into
# results.eln.tags. That's what lets the "Tabular Data" Explore app
# (apps/tabular_guess.py) find exactly the entries this plugin produced,
# regardless of their per-upload section name.
ELN_TAG = 'nomad_auto_upload_tables'
ELN_BASE_SECTION = 'nomad.datamodel.metainfo.eln.ElnBaseSection'
# ElnBaseSection also predefines name/datetime/lab_id/description, which this
# plugin doesn't populate; hide them so the generated entry's edit form only
# shows the columns imported from the table.
ELN_HIDDEN_QUANTITIES = ['name', 'datetime', 'lab_id', 'description', 'tags']

X_CATEGORY_PRIORITY = (
    'time',
    'length',
    'particle_diameter',
    'temperature',
    'pressure',
)
X_NAME_PRIORITY = (
    'particle_diameter',
    'diameter',
    'time',
    'length',
    'temperature',
    'pressure',
)
Y_CATEGORY_PRIORITY = (
    'measurement_result',
    'intensity',
    'signal',
    'mass',
    'undersize',
    'distribution',
)
Y_NAME_PRIORITY = (
    'volume_distribution',
    'undersize_distribution',
    'distribution',
    'intensity',
    'signal',
    'measurement_result',
    'mass',
)
NUMERIC_TYPES = {'float', 'integer'}
PLOT_TYPES = (
    'xy_scatter',
    'xy_line',
    'area',
    'bar',
    'histogram',
    'box',
    'violin',
    'heatmap',
    'scatter_3d',
    'colored_scatter',
)
PLOT_TYPE_FIELDS = {
    'xy_scatter': 'enable_xy_scatter',
    'xy_line': 'enable_xy_line',
    'area': 'enable_area',
    'bar': 'enable_bar',
    'histogram': 'enable_histogram',
    'box': 'enable_box',
    'violin': 'enable_violin',
    'heatmap': 'enable_heatmap',
    'scatter_3d': 'enable_scatter_3d',
    'colored_scatter': 'enable_colored_scatter',
}

MATERIAL_FORMULA_TOKENS = ('chemical_formula', 'formula', 'composition', 'material')
MATERIAL_NAME_TOKENS = ('material_name', 'material', 'sample_name', 'sample_id')
METHOD_TOKENS = ('method', 'measurement_method', 'technique', 'workflow')
STRUCTURAL_TYPES = {'bulk', 'surface', '2D', '1D', 'molecule', 'atom', 'unavailable'}
DIMENSIONALITIES = {'0D', '1D', '2D', '3D', 'unavailable'}
METHOD_NAMES = {'BSE', 'CoreHole', 'DFT', 'DMFT', 'EELS', 'GW', 'NMR', 'TB', 'XPS', 'XRD', 'kMC', 'quantum cms', 'unavailable'}
ELEMENT_SYMBOLS = {
    'H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne',
    'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar', 'K', 'Ca',
    'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn',
    'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr', 'Rb', 'Sr', 'Y', 'Zr',
    'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn',
    'Sb', 'Te', 'I', 'Xe', 'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd',
    'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb',
    'Lu', 'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg',
    'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn', 'Fr', 'Ra', 'Ac', 'Th',
    'Pa', 'U', 'Np', 'Pu', 'Am', 'Cm', 'Bk', 'Cf', 'Es', 'Fm',
    'Md', 'No', 'Lr', 'Rf', 'Db', 'Sg', 'Bh', 'Hs', 'Mt', 'Ds',
    'Rg', 'Cn', 'Nh', 'Fl', 'Mc', 'Lv', 'Ts', 'Og',
}
ELEMENT_SYMBOLS_LOWER = {symbol.lower(): symbol for symbol in ELEMENT_SYMBOLS}


@dataclass(frozen=True)
class GeneratedArtifacts:
    schema_file: str
    entry_file: str
    section_name: str
    schema_yaml: str
    entry_yaml: str
    enabled_plots: tuple[str, ...] = ()
    plot_columns: tuple[str, ...] = ()
    plot_label: str | None = None
    mapping_mode: str = 'column'


def build_generated_artifacts(entry) -> GeneratedArtifacts:
    base = _base_name(entry.data_file or 'table')
    mapping_mode = str(getattr(entry, 'mapping_mode', None) or 'column')
    section_name = _section_name(getattr(entry, 'generated_section_name', None), base, entry.columns)
    columns = _included_columns(entry.columns)

    if mapping_mode == 'row':
        schema_file = _row_schema_path(getattr(entry, 'generated_schema_file', None), base)
        schema_dict = build_row_schema_dict(
            section_name=section_name,
            schema_name=f'{_title_from_identifier(section_name)} row schema',
            columns=columns,
        )
        return GeneratedArtifacts(
            schema_file=schema_file,
            entry_file='',
            section_name=section_name,
            schema_yaml=_dump_yaml(schema_dict),
            entry_yaml='',
            mapping_mode='row',
        )

    schema_file = _defaulted_path(getattr(entry, 'generated_schema_file', None), SCHEMA_DIR, f'{base}_schema.archive.yaml')
    entry_file = _defaulted_path(getattr(entry, 'generated_entry_file', None), ENTRY_DIR, f'{base}_entry.archive.yaml')
    enabled_plots, plot_columns, plot_label = _plot_config_from_entry(entry, columns)

    schema_dict = build_schema_dict(
        section_name=section_name,
        schema_name=f'{_title_from_identifier(section_name)} schema',
        columns=columns,
        sheet_name=_excel_sheet_name(getattr(entry, 'data_file', None), getattr(entry, 'sheet_name', None)),
        enabled_plots=enabled_plots,
        plot_columns=plot_columns,
        plot_label=plot_label,
        all_combination_plots=bool(getattr(entry, 'enable_all_combination_plots', False)),
    )
    entry_dict = build_entry_dict(
        schema_file=schema_file,
        entry_file=entry_file,
        section_name=section_name,
        data_file=entry.data_file,
        results_config=_results_config_from_entry(entry),
    )

    return GeneratedArtifacts(
        schema_file=schema_file,
        entry_file=entry_file,
        section_name=section_name,
        schema_yaml=_dump_yaml(schema_dict),
        entry_yaml=_dump_yaml(entry_dict),
        enabled_plots=tuple(enabled_plots),
        plot_columns=tuple(plot_columns),
        plot_label=plot_label,
        mapping_mode='column',
    )


def build_row_schema_dict(
    *,
    section_name: str,
    schema_name: str,
    columns: list,
) -> dict[str, Any]:
    quantities: dict[str, Any] = {
        'source_file': {
            'type': 'str',
            'description': 'Original uploaded table file this row was generated from.',
        },
        'source_row': {
            'type': 'np.int64',
            'description': 'One-based source table row number.',
        },
    }
    order = ['source_file', 'source_row']
    for column in columns:
        quantity_name = _quantity_name(column)
        order.append(quantity_name)
        quantity = {
            'type': _yaml_type(column.guessed_type),
            'description': _description(column),
        }
        unit = _canonical_unit(getattr(column, 'guessed_unit', '') or '', quantity_name, getattr(column, 'category', ''))
        if unit:
            quantity['unit'] = unit
        quantities[quantity_name] = quantity
    quantities['tags'] = _tags_quantity()

    section: dict[str, Any] = {
        # ElnBaseSection must come first: see the comment on the column-mode
        # base_sections list below for why order here isn't cosmetic.
        'base_sections': [ELN_BASE_SECTION, 'nomad.datamodel.data.EntryData'],
        'm_annotations': {'eln': {'hide': ELN_HIDDEN_QUANTITIES, 'properties': {'order': order}}},
        'quantities': quantities,
    }
    label_quantity = _label_quantity(columns)
    if label_quantity:
        section['more'] = {'label_quantity': label_quantity}

    return {
        'definitions': {
            'name': schema_name,
            'sections': {section_name: section},
        }
    }


def build_schema_dict(
    *,
    section_name: str,
    schema_name: str,
    columns: list,
    sheet_name: str | None = None,
    enabled_plots: list[str] | tuple[str, ...] = (),
    plot_columns: list[str] | tuple[str, ...] = (),
    plot_label: str | None,
    all_combination_plots: bool = False,
) -> dict[str, Any]:
    quantities: dict[str, Any] = {
        'data_file': {
            'type': 'str',
            'm_annotations': {
                'tabular_parser': {
                    'parsing_options': {'comment': '#'},
                    'mapping_options': [
                        {
                            'mapping_mode': 'column',
                            'file_mode': 'current_entry',
                            'sections': ['#root'],
                        }
                    ],
                },
                'browser': {'adaptor': 'RawFileAdaptor'},
                'eln': {'component': 'FileEditQuantity'},
            },
        }
    }
    order = ['data_file']
    for column in columns:
        quantity_name = _quantity_name(column)
        order.append(quantity_name)
        quantity = {
            'type': _yaml_type(column.guessed_type),
            'shape': ['*'],
            'description': _description(column),
        }
        tabular_name = _tabular_column_name(column, sheet_name)
        if tabular_name:
            quantity['m_annotations'] = {'tabular': {'name': tabular_name}}
        else:
            quantity['description'] = (
                f'{quantity["description"]} This column header contains "/" and cannot be '
                'addressed safely by NOMAD tabular column mapping, so it is not auto-imported.'
            )
        unit = _canonical_unit(getattr(column, 'guessed_unit', '') or '', quantity_name, getattr(column, 'category', ''))
        if unit:
            quantity['unit'] = unit
        quantities[quantity_name] = quantity

    annotations: dict[str, Any] = {
        'eln': {'hide': ELN_HIDDEN_QUANTITIES, 'properties': {'order': order}},
    }
    if all_combination_plots:
        plotly_graph_objects = _build_combination_plots(columns, quantities)
    else:
        plotly_graph_objects = _build_plotly_graph_objects(enabled_plots, plot_columns, plot_label, quantities)
    if plotly_graph_objects:
        annotations['plotly_graph_object'] = plotly_graph_objects
    quantities['tags'] = _tags_quantity()
    section: dict[str, Any] = {
        # ElnBaseSection must be listed first, matching NOMAD's own convention
        # (see BasicEln(ElnBaseSection, EntryData) in nomad.datamodel.metainfo.eln).
        # ElnBaseSection.normalize() explicitly re-invokes EntryData.normalize(self, ...)
        # after its own super().normalize() call already ran it once; that
        # explicit call's own super() resolves against the *instance's* full
        # MRO, so if EntryData comes before ElnBaseSection here, that second
        # call chains straight back into ElnBaseSection.normalize() again -
        # infinite recursion (confirmed empirically, not theoretical). With
        # ElnBaseSection first, EntryData's super() chain never loops back.
        'base_sections': [
            ELN_BASE_SECTION,
            'nomad.datamodel.data.EntryData',
            'nomad.parsing.tabular.TableData',
            'nomad.datamodel.metainfo.plot.PlotSection',
        ],
        'm_annotations': annotations,
        'quantities': quantities,
    }
    label_quantity = _label_quantity(columns)
    if label_quantity:
        section['more'] = {'label_quantity': label_quantity}

    return {
        'definitions': {
            'name': schema_name,
            'sections': {
                section_name: section,
            },
        }
    }


def build_entry_dict(
    *,
    schema_file: str,
    entry_file: str,
    section_name: str,
    data_file: str,
    results_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        'data': {
            'm_def': f'../uploads/archive/mainfile/{schema_file}#/definitions/sections/{section_name}',
            'data_file': str(data_file).strip().lstrip('/'),
            'fill_archive_from_datafile': True,
            # ElnBaseSection.normalize() (inherited via ELN_BASE_SECTION) falls
            # back to `archive.metadata.entry_name.split('.')...` when `name` is
            # unset, and entry_name isn't populated yet at that point for these
            # generated entries - it crashes with AttributeError on None. Setting
            # name here avoids that path entirely, and doubles as a readable
            # entry_name (ElnBaseSection copies it there when both are set).
            'name': _title_from_identifier(section_name),
        }
    }
    results = build_results_dict(results_config or {})
    if results:
        entry['results'] = results
    return entry


def generated_review_file(data_file: str) -> str:
    base = _base_name(data_file)
    return f'{REVIEW_DIR}/{base}_review.archive.yaml'


def build_review_dict(
    *,
    data_file: str,
    sheet_name: str | None,
    n_rows: int,
    ai_assisted: bool,
    columns: list[dict],
    plot_suggestions: dict | None = None,
) -> dict[str, Any]:
    base = _base_name(data_file)
    generated_schema_file = f'{SCHEMA_DIR}/{base}_schema.archive.yaml'
    generated_entry_file = f'{ENTRY_DIR}/{base}_entry.archive.yaml'
    section_name = _section_name(None, base, [type('Column', (), c) for c in columns])
    included_columns = [type('Column', (), c) for c in columns if c.get('include', True) is not False]
    enabled_plots, plot_columns, plot_label = _review_plot_defaults(included_columns, plot_suggestions)
    results_defaults = _review_results_defaults(included_columns, plot_suggestions)
    return {
        'data': {
            'm_def': 'nomad_auto_upload_tables.schema_packages.tabular_guess.TabularGuess',
            'data_file': data_file,
            'sheet_name': sheet_name,
            'n_rows': n_rows,
            'ai_assisted': ai_assisted,
            'generated_section_name': section_name,
            'generated_schema_file': generated_schema_file,
            'generated_entry_file': generated_entry_file,
            'mapping_mode': 'column',
            'enable_xy_scatter': 'xy_scatter' in enabled_plots,
            'enable_xy_line': 'xy_line' in enabled_plots,
            'enable_area': 'area' in enabled_plots,
            'enable_bar': 'bar' in enabled_plots,
            'enable_histogram': 'histogram' in enabled_plots,
            'enable_box': 'box' in enabled_plots,
            'enable_violin': 'violin' in enabled_plots,
            'enable_heatmap': 'heatmap' in enabled_plots,
            'enable_scatter_3d': 'scatter_3d' in enabled_plots,
            'enable_colored_scatter': 'colored_scatter' in enabled_plots,
            'plot_label': plot_label,
            'plot_columns': ', '.join(plot_columns),
            'enable_results_material': bool(results_defaults.get('material_formula')),
            'material_formula': results_defaults.get('material_formula') or '',
            'material_name': results_defaults.get('material_name') or '',
            'structural_type': results_defaults.get('structural_type') or '',
            'dimensionality': results_defaults.get('dimensionality') or '',
            'enable_results_method': bool(results_defaults.get('method_name') or results_defaults.get('workflow_name')),
            'method_name': results_defaults.get('method_name') or '',
            'workflow_name': results_defaults.get('workflow_name') or '',
            'columns': columns,
        }
    }


def dump_review_yaml(
    *,
    data_file: str,
    sheet_name: str | None,
    n_rows: int,
    columns: list[dict],
    ai_assisted: bool,
    plot_suggestions: dict | None = None,
) -> str:
    return _dump_yaml(
        build_review_dict(
            data_file=data_file,
            sheet_name=sheet_name,
            n_rows=n_rows,
            columns=columns,
            ai_assisted=ai_assisted,
            plot_suggestions=plot_suggestions,
        )
    )


def build_results_dict(config: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    if config.get('enable_results_material'):
        material = _material_results_dict(
            formula=config.get('material_formula'),
            material_name=config.get('material_name'),
            structural_type=config.get('structural_type'),
            dimensionality=config.get('dimensionality'),
        )
        if material:
            results['material'] = material
    if config.get('enable_results_method'):
        method = _method_results_dict(
            method_name=config.get('method_name'),
            workflow_name=config.get('workflow_name'),
        )
        if method:
            results['method'] = method
    return results


def _material_results_dict(
    *,
    formula: str | None,
    material_name: str | None = None,
    structural_type: str | None = None,
    dimensionality: str | None = None,
) -> dict[str, Any]:
    clean_formula = normalize_material_formula(formula)
    if not clean_formula:
        return {}
    try:
        from nomad.atomutils import Formula
        from nomad.datamodel.results import Material

        material = Material()
        Formula(clean_formula).populate(material, overwrite=True)
        material_dict = material.m_to_dict()
    except Exception:
        return {}

    clean_name = str(material_name or '').strip()
    if clean_name:
        material_dict['material_name'] = clean_name
    clean_structural_type = str(structural_type or '').strip()
    if clean_structural_type in STRUCTURAL_TYPES:
        material_dict['structural_type'] = clean_structural_type
    clean_dimensionality = str(dimensionality or '').strip()
    if clean_dimensionality in DIMENSIONALITIES:
        material_dict['dimensionality'] = clean_dimensionality
    return material_dict


def _method_results_dict(*, method_name: str | None = None, workflow_name: str | None = None) -> dict[str, Any]:
    method: dict[str, Any] = {}
    clean_method = str(method_name or '').strip()
    clean_workflow = str(workflow_name or '').strip()
    if clean_method in METHOD_NAMES:
        method['method_name'] = clean_method
    if clean_workflow:
        method['workflow_name'] = clean_workflow
    return method


def _results_config_from_entry(entry) -> dict[str, Any]:
    return {
        'enable_results_material': bool(getattr(entry, 'enable_results_material', False)),
        'material_formula': getattr(entry, 'material_formula', None),
        'material_name': getattr(entry, 'material_name', None),
        'structural_type': getattr(entry, 'structural_type', None),
        'dimensionality': getattr(entry, 'dimensionality', None),
        'enable_results_method': bool(getattr(entry, 'enable_results_method', False)),
        'method_name': getattr(entry, 'method_name', None),
        'workflow_name': getattr(entry, 'workflow_name', None),
    }


def _review_results_defaults(columns, suggestions: dict | None) -> dict[str, str]:
    defaults = {
        'material_formula': _single_valid_formula_from_columns(columns),
        'material_name': _single_value_from_columns(columns, MATERIAL_NAME_TOKENS),
        'method_name': _single_value_from_columns(columns, METHOD_TOKENS),
        'workflow_name': '',
        'structural_type': '',
        'dimensionality': '',
    }
    if isinstance(suggestions, dict):
        material = _clean_material_suggestion(suggestions.get('material_suggestion'))
        method = _clean_method_suggestion(suggestions.get('method_suggestion'))
        defaults.update({key: value for key, value in material.items() if value})
        defaults.update({key: value for key, value in method.items() if value})
    return defaults


def _clean_material_suggestion(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    material: dict[str, str] = {}
    formula = normalize_material_formula(value.get('material_formula') or value.get('formula'))
    if formula:
        material['material_formula'] = formula
    name = str(value.get('material_name') or value.get('name') or '').strip()
    if name:
        material['material_name'] = name
    structural_type = str(value.get('structural_type') or '').strip()
    if structural_type in STRUCTURAL_TYPES:
        material['structural_type'] = structural_type
    dimensionality = str(value.get('dimensionality') or '').strip()
    if dimensionality in DIMENSIONALITIES:
        material['dimensionality'] = dimensionality
    return material


def _clean_method_suggestion(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    method_name = str(value.get('method_name') or value.get('name') or '').strip()
    workflow_name = str(value.get('workflow_name') or value.get('workflow') or '').strip()
    result: dict[str, str] = {}
    if method_name:
        result['method_name'] = method_name
    if workflow_name:
        result['workflow_name'] = workflow_name
    return result


def _single_valid_formula_from_columns(columns) -> str:
    values = _single_values_by_tokens(columns, MATERIAL_FORMULA_TOKENS)
    valid = [formula for value in values if (formula := normalize_material_formula(value))]
    return valid[0] if len(valid) == 1 else ''


def _single_value_from_columns(columns, tokens: tuple[str, ...]) -> str:
    values = _single_values_by_tokens(columns, tokens)
    return values[0] if len(values) == 1 else ''


def _single_values_by_tokens(columns, tokens: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for column in columns:
        name = _quantity_name(column)
        header = safe_quantity_name(getattr(column, 'header', ''), fallback_header=str(getattr(column, 'header', '')))
        if not any(token == name or token in name or token == header or token in header for token in tokens):
            continue
        sample_values = _sample_values(getattr(column, 'sample_values', ''))
        if len(sample_values) == 1 and sample_values[0] not in values:
            values.append(sample_values[0])
    return values


def _sample_values(value: str | None) -> list[str]:
    parts = [part.strip() for part in str(value or '').split(',')]
    return [part for part in parts if part]


def normalize_material_formula(value: str | None) -> str:
    """Return a NOMAD-parseable formula from a formula-like label.

    Tables and AI responses often contain labels such as ``al2o3_based`` or
    ``Al2O3-based``. NOMAD's Formula parser needs the real formula token with
    proper element casing, so we extract conservatively and validate against
    real element symbols.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    candidates = [text]
    candidates.extend(re.findall(r'[A-Za-z][A-Za-z0-9().]*', text))
    for candidate in candidates:
        formula = _canonical_formula_token(candidate)
        if _is_valid_formula(formula):
            return formula
    return ''


def _canonical_formula_token(value: str | None) -> str:
    formula = str(value or '').strip().strip('.,;:')
    if not formula:
        return ''
    if re.search(r'[A-Z][a-z]?', formula):
        return formula

    result = []
    index = 0
    while index < len(formula):
        char = formula[index]
        if char.isdigit() or char in '().':
            result.append(char)
            index += 1
            continue
        if not char.isalpha():
            return ''

        two = formula[index : index + 2].lower()
        one = formula[index].lower()
        if len(two) == 2 and two in ELEMENT_SYMBOLS_LOWER:
            result.append(ELEMENT_SYMBOLS_LOWER[two])
            index += 2
        elif one in ELEMENT_SYMBOLS_LOWER:
            result.append(ELEMENT_SYMBOLS_LOWER[one])
            index += 1
        else:
            return ''
    return ''.join(result)


def _is_valid_formula(value: str | None) -> bool:
    formula = str(value or '').strip()
    if not formula:
        return False
    try:
        from nomad.atomutils import Formula

        elements = Formula(formula).elements()
    except Exception:
        return False
    return bool(elements) and all(element in ELEMENT_SYMBOLS for element in elements)

def _review_plot_defaults(columns, plot_suggestions: dict | None) -> tuple[list[str], list[str], str | None]:
    default_columns = _default_plot_columns(columns)
    default_enabled = ['xy_scatter'] if len(default_columns) >= 2 else []
    default_label = _default_plot_label(columns, default_columns)
    if not isinstance(plot_suggestions, dict):
        return default_enabled, default_columns, default_label

    suggested_columns = _validate_suggested_plot_columns(plot_suggestions.get('plot_columns'), columns)
    plot_columns = suggested_columns or default_columns
    suggested_enabled = _validate_suggested_plot_types(plot_suggestions.get('enabled_plots'), plot_columns)
    enabled_plots = suggested_enabled or default_enabled
    plot_label = str(plot_suggestions.get('plot_label') or '').strip() or default_label
    return enabled_plots, plot_columns, plot_label


def _validate_suggested_plot_columns(value, columns) -> list[str]:
    numeric_names = {_quantity_name(column) for column in columns if getattr(column, 'guessed_type', None) in NUMERIC_TYPES}
    if isinstance(value, str):
        candidates = [part.strip() for part in value.split(',')]
    elif isinstance(value, (list, tuple)):
        candidates = value
    else:
        candidates = []
    selected = []
    for candidate in candidates:
        name = safe_quantity_name(candidate, fallback_header=str(candidate or ''))
        if name in numeric_names and name not in selected:
            selected.append(name)
    return selected


def _validate_suggested_plot_types(value, plot_columns: list[str]) -> list[str]:
    if isinstance(value, str):
        candidates = [part.strip() for part in value.split(',')]
    elif isinstance(value, (list, tuple)):
        candidates = value
    else:
        candidates = []
    enabled = []
    for candidate in candidates:
        plot_type = str(candidate or '').strip()
        if plot_type in PLOT_TYPES and plot_type not in enabled and _plot_type_has_enough_columns(plot_type, plot_columns):
            enabled.append(plot_type)
    return enabled


def _plot_type_has_enough_columns(plot_type: str, plot_columns: list[str] | tuple[str, ...]) -> bool:
    required = 3 if plot_type in {'heatmap', 'scatter_3d', 'colored_scatter'} else 2 if plot_type in {'xy_scatter', 'xy_line', 'area', 'bar'} else 1
    return len(plot_columns) >= required

def _plot_config_from_entry(entry, columns) -> tuple[list[str], list[str], str | None]:
    selected_columns = _valid_plot_columns(getattr(entry, 'plot_columns', None), columns)
    if not selected_columns:
        selected_columns = _default_plot_columns(columns)

    enabled = [plot_type for plot_type, field in PLOT_TYPE_FIELDS.items() if getattr(entry, field, False)]
    if not enabled and len(selected_columns) >= 2:
        enabled = ['xy_scatter']

    label = str(getattr(entry, 'plot_label', '') or '').strip() or _default_plot_label(columns, selected_columns)
    return enabled, selected_columns, label


def _valid_plot_columns(value: str | None, columns) -> list[str]:
    numeric_names = {_quantity_name(column) for column in columns if getattr(column, 'guessed_type', None) in NUMERIC_TYPES}
    selected: list[str] = []
    for raw in str(value or '').split(','):
        name = safe_quantity_name(raw.strip(), fallback_header=raw.strip()) if raw.strip() else ''
        if name in numeric_names and name not in selected:
            selected.append(name)
    return selected


def _default_plot_columns(columns) -> list[str]:
    numeric = [column for column in columns if getattr(column, 'guessed_type', None) in NUMERIC_TYPES]
    if not numeric:
        return []
    names = [_quantity_name(column) for column in numeric]
    if _looks_like_psd(columns):
        preferred = ['particle_diameter', 'volume_distribution', 'undersize_distribution']
        return [name for name in preferred if name in names] + [name for name in names if name not in preferred]

    plot_x, plot_y = _select_plot_columns(columns)
    ordered = [name for name in (plot_x, plot_y) if name]
    return ordered + [name for name in names if name not in ordered]


def _default_plot_label(columns, plot_columns: list[str]) -> str | None:
    if _looks_like_psd(columns):
        return 'PSD curve'
    if plot_columns:
        return _title_from_identifier(plot_columns[-1])
    return None


def _build_plotly_graph_objects(
    enabled_plots: list[str] | tuple[str, ...],
    plot_columns: list[str] | tuple[str, ...],
    plot_label: str | None,
    quantities: dict[str, Any],
) -> list[dict[str, Any]]:
    selected = [name for name in plot_columns if name in quantities]
    graph_objects: list[dict[str, Any]] = []
    for plot_type in PLOT_TYPES:
        if plot_type not in enabled_plots:
            continue
        graph = _plotly_graph_object(plot_type, selected, plot_label or 'Plot', quantities)
        if graph is None:
            continue
        graph_objects.append(graph)
    return _finalize_graph_objects(graph_objects)


# Cap on auto-generated combination figures. A wide table has O(n^2) numeric
# pairs alone; this keeps generation and the resulting entry reasonable while
# still covering the overwhelming majority of real tables (n <= ~9 numeric
# columns fits under this without truncation).
MAX_COMBINATION_PLOTS = 40


def _build_combination_plots(columns: list, quantities: dict[str, Any]) -> list[dict[str, Any]]:
    """One scatter per pair of numeric columns, one bar chart per
    (categorical, numeric) column pair, and one standalone bar chart per
    numeric column (values in row order) - all as separate figures, so
    NOMAD's entry Overview plot picker (see the `label` on each figure) lets
    you switch between every meaningful column combination.

    This exists because NOMAD's cross-upload Explore dashboard widgets can't
    do this job: each upload gets its own one-off generated schema class, so
    there's no shared, stable search_quantity path a dashboard widget could
    bind to across uploads (see apps/__init__.py). Per-entry PlotSection
    figures don't have that problem - they're scoped to the one schema this
    function already has in hand.
    """
    numeric_names = [
        name for c in columns
        if getattr(c, 'guessed_type', None) in NUMERIC_TYPES and (name := _quantity_name(c)) in quantities
    ]
    string_names = [
        name for c in columns
        if getattr(c, 'guessed_type', None) == 'string' and (name := _quantity_name(c)) in quantities
    ]

    graphs: list[dict[str, Any]] = []

    for index, x in enumerate(numeric_names):
        for y in numeric_names[index + 1 :]:
            if len(graphs) >= MAX_COMBINATION_PLOTS:
                return _finalize_graph_objects(graphs)
            label = f'{_title_from_identifier(y)} vs {_title_from_identifier(x)}'
            graphs.append({
                'label': label,
                'data': {'x': f'#{x}', 'y': f'#{y}', 'type': 'scatter', 'mode': 'markers', 'name': _title_from_identifier(y)},
                'layout': _xy_layout(label, x, y, quantities),
            })

    for category in string_names:
        for value in numeric_names:
            if len(graphs) >= MAX_COMBINATION_PLOTS:
                return _finalize_graph_objects(graphs)
            label = f'{_title_from_identifier(value)} by {_title_from_identifier(category)}'
            graphs.append({
                'label': label,
                'data': {'x': f'#{category}', 'y': f'#{value}', 'type': 'bar', 'name': _title_from_identifier(value)},
                'layout': _xy_layout(label, category, value, quantities),
            })

    for value in numeric_names:
        if len(graphs) >= MAX_COMBINATION_PLOTS:
            return _finalize_graph_objects(graphs)
        label = _title_from_identifier(value)
        graphs.append({
            'label': _plot_object_label(label, 'bar'),
            'data': {'y': f'#{value}', 'type': 'bar', 'name': label},
            'layout': {
                'title': {'text': label},
                'yaxis': {'title': {'text': _axis_title(value, quantities[value].get('unit'))}},
            },
        })

    return _finalize_graph_objects(graphs)


def _finalize_graph_objects(graphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, graph in enumerate(graphs):
        graph['index'] = index
        graph['open'] = index == 0
    return graphs


def _plotly_graph_object(plot_type: str, columns: list[str], label: str, quantities: dict[str, Any]) -> dict[str, Any] | None:
    if plot_type in {'xy_scatter', 'xy_line', 'area', 'bar'}:
        if len(columns) < 2:
            return None
        x, y = columns[:2]
        if plot_type == 'bar':
            data = {'x': f'#{x}', 'y': f'#{y}', 'type': 'bar', 'name': _title_from_identifier(y)}
            suffix = 'bar'
        elif plot_type == 'area':
            data = {'x': f'#{x}', 'y': f'#{y}', 'type': 'scatter', 'mode': 'lines', 'fill': 'tozeroy', 'name': _title_from_identifier(y)}
            suffix = 'area'
        else:
            mode = 'lines+markers' if plot_type == 'xy_scatter' else 'lines'
            data = {'x': f'#{x}', 'y': f'#{y}', 'type': 'scatter', 'mode': mode, 'name': _title_from_identifier(y)}
            suffix = 'line' if plot_type == 'xy_line' else ''
        return {
            'label': _plot_object_label(label, suffix),
            'data': data,
            'layout': _xy_layout(label, x, y, quantities),
        }

    if plot_type in {'histogram', 'box', 'violin'}:
        if not columns:
            return None
        value_column = columns[1] if len(columns) > 1 and plot_type in {'box', 'violin'} else columns[0]
        axis = 'x' if plot_type == 'histogram' else 'y'
        return {
            'label': _plot_object_label(label, plot_type),
            'data': {
                axis: f'#{value_column}',
                'type': plot_type,
                'name': _title_from_identifier(value_column),
            },
            'layout': {'title': {'text': _plot_object_label(label, plot_type)}},
        }

    if plot_type == 'colored_scatter':
        if len(columns) < 3:
            return None
        x, y, color = columns[:3]
        return {
            'label': _plot_object_label(label, 'colored scatter'),
            'data': {
                'x': f'#{x}',
                'y': f'#{y}',
                'type': 'scatter',
                'mode': 'markers',
                'marker': {'color': f'#{color}', 'colorscale': 'Viridis', 'showscale': True},
                'name': _title_from_identifier(y),
            },
            'layout': _xy_layout(label, x, y, quantities),
        }

    if plot_type == 'heatmap':
        if len(columns) < 3:
            return None
        x, y, z = columns[:3]
        return {
            'label': _plot_object_label(label, 'heatmap'),
            'data': {'x': f'#{x}', 'y': f'#{y}', 'z': f'#{z}', 'type': 'heatmap'},
            'layout': _xy_layout(label, x, y, quantities),
        }

    if plot_type == 'scatter_3d':
        if len(columns) < 3:
            return None
        x, y, z = columns[:3]
        return {
            'label': _plot_object_label(label, '3D'),
            'data': {
                'x': f'#{x}',
                'y': f'#{y}',
                'z': f'#{z}',
                'type': 'scatter3d',
                'mode': 'markers',
                'name': _title_from_identifier(z),
            },
            'layout': {'title': {'text': _plot_object_label(label, '3D')}},
        }

    return None


def _xy_layout(label: str, x: str, y: str, quantities: dict[str, Any]) -> dict[str, Any]:
    return {
        'title': {'text': _plot_title_from_label(label)},
        'xaxis': {'title': {'text': _axis_title(x, quantities[x].get('unit'))}},
        'yaxis': {'title': {'text': _axis_title(y, quantities[y].get('unit'))}},
    }


def _plot_object_label(label: str, suffix: str) -> str:
    clean = str(label or 'Plot').strip() or 'Plot'
    return f'{clean} {suffix}'.strip() if suffix else clean


def _plot_title_from_label(label: str) -> str:
    if str(label).lower() == 'psd curve':
        return 'Particle size distribution'
    return label

def _included_columns(columns) -> list:
    return [column for column in columns if getattr(column, 'include', True) is not False]


def _quantity_name(column) -> str:
    return safe_quantity_name(getattr(column, 'guessed_name', None), fallback_header=str(column.header))


def _tags_quantity() -> dict[str, Any]:
    return {
        'type': 'str',
        'shape': ['*'],
        'default': [ELN_TAG],
        'description': (
            'Fixed marker tag copied into results.eln.tags by ElnBaseSection, '
            'used by the "Tabular Data" Explore app to find entries generated '
            'by nomad-auto-upload-tables.'
        ),
    }


def _base_name(path: str) -> str:
    name = PurePosixPath(str(path)).name
    for suffix in ('.archive.yaml', '.archive.yml', '.archive.json'):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    else:
        name = PurePosixPath(name).stem
    return safe_quantity_name(name, fallback_header='table')


def _row_schema_path(value: str | None, base: str) -> str:
    column_default = f'{SCHEMA_DIR}/{base}_schema.archive.yaml'
    row_default = f'{SCHEMA_DIR}/{base}_row_schema.archive.yaml'
    clean = str(value or '').strip().lstrip('/')
    if not clean or clean == column_default:
        return row_default
    return clean


def _defaulted_path(value: str | None, directory: str, default_name: str) -> str:
    if value:
        return str(value).strip().lstrip('/')
    return f'{directory}/{default_name}'


def _relative_ref(from_file: str, target_path: str) -> str:
    target = str(target_path).strip().lstrip('/')
    source_parent = PurePosixPath(str(from_file).strip().lstrip('/')).parent
    if source_parent == PurePosixPath('.'):
        return target

    parent_parts = [part for part in source_parent.parts if part not in ('', '.')]
    relative = PurePosixPath(*(['..'] * len(parent_parts)), target)
    return relative.as_posix()


def _section_name(value: str | None, base: str, columns) -> str:
    if value:
        words = re.split(r'[^0-9a-zA-Z]+', str(value))
    elif _looks_like_psd(columns):
        words = ['Particle', 'Size', 'Distribution']
    else:
        words = base.split('_')
    name = ''.join(word[:1].upper() + word[1:] for word in words if word)
    if not name:
        name = 'GeneratedTable'
    if name[0].isdigit():
        name = f'Generated{name}'
    return name


def _looks_like_psd(columns) -> bool:
    names = {_quantity_name(column) for column in columns}
    return 'particle_diameter' in names and any('distribution' in name for name in names)


def _yaml_type(guessed_type: str) -> str:
    return {
        'string': 'str',
        'integer': 'np.int64',
        'float': 'np.float64',
        'boolean': 'bool',
        'datetime': 'Datetime',
    }.get(guessed_type, 'str')


def _canonical_unit(unit: str, quantity_name: str, category: str) -> str:
    clean = safe_unit(unit)
    lower = clean.lower()
    if lower in {'%', 'percent'}:
        return _nomad_safe_unit('percent')
    if lower in {'um', 'µm', 'micrometer', 'micrometre'}:
        return _nomad_safe_unit('micrometer')
    clean = _normalize_unit_for_nomad(clean)
    if not clean:
        if 'diameter' in quantity_name or category == 'length':
            return _nomad_safe_unit('micrometer') if 'particle' in quantity_name or 'diameter' in quantity_name else ''
        if 'distribution' in quantity_name or 'undersize' in quantity_name:
            return _nomad_safe_unit('percent')
    return _nomad_safe_unit(clean)


def _excel_sheet_name(data_file: str | None, sheet_name: str | None) -> str | None:
    if not str(data_file or '').lower().endswith(('.xlsx', '.xls')):
        return None
    sheet = str(sheet_name or '').strip()
    return sheet or None


def _tabular_column_name(column, sheet_name: str | None) -> str | None:
    header = str(getattr(column, 'header', '') or '').strip()
    if not header or '/' in header:
        return None
    if sheet_name:
        return f'{sheet_name}/{header}'
    return header


def _normalize_unit_for_nomad(unit: str) -> str:
    clean = str(unit or '').strip()
    if not clean:
        return ''
    # NOMAD's unit registry treats "min" as milliinch. Use the unambiguous
    # time unit spelling for rates like cm^3/min and m/min.
    clean = re.sub(r'(?<=/)\s*min\b', 'minute', clean)
    clean = re.sub(r'(?<=\*)\s*min\b', 'minute', clean)
    return clean


def _nomad_safe_unit(unit: str) -> str:
    clean = str(unit or '').strip()
    if not clean:
        return ''
    try:
        from nomad.units import ureg

        parsed = ureg.Quantity(1, clean)
        if 'milliinch' in str(parsed.units):
            return ''
    except Exception:
        return ''
    return clean


def _description(column) -> str:
    header = str(getattr(column, 'header', '') or '')
    category = str(getattr(column, 'category', '') or '')
    if category and category != 'other':
        return f'Imported from column {header!r}; guessed category: {category}.'
    return f'Imported from column {header!r}.'


def _label_quantity(columns) -> str | None:
    for column in columns:
        name = _quantity_name(column)
        if name in {'sample_id', 'sample_name'}:
            return name
    return None


def _select_plot_columns(columns, *, preferred_x: str | None = None, preferred_y: str | None = None) -> tuple[str | None, str | None]:
    numeric = [column for column in columns if getattr(column, 'guessed_type', None) in NUMERIC_TYPES]
    if len(numeric) < 2:
        return None, None
    names = {_quantity_name(column): column for column in numeric}
    x = _preferred_column(names, preferred_x) or _ranked_column(numeric, X_NAME_PRIORITY, X_CATEGORY_PRIORITY) or _quantity_name(numeric[0])
    y_candidates = [column for column in numeric if _quantity_name(column) != x]
    y_names = {_quantity_name(column): column for column in y_candidates}
    y = _preferred_column(y_names, preferred_y) or _ranked_column(y_candidates, Y_NAME_PRIORITY, Y_CATEGORY_PRIORITY)
    if y is None and y_candidates:
        y = _quantity_name(y_candidates[0])
    if not y or x == y:
        return None, None
    return x, y


def _preferred_column(names: dict, preferred: str | None) -> str | None:
    if not preferred:
        return None
    clean = safe_quantity_name(preferred, fallback_header=preferred)
    return clean if clean in names else None


def _ranked_column(columns, name_priority: tuple[str, ...], category_priority: tuple[str, ...]) -> str | None:
    by_name = {_quantity_name(column): column for column in columns}
    for token in name_priority:
        for name in by_name:
            if token == name or token in name:
                return name
    for category in category_priority:
        for column in columns:
            column_category = str(getattr(column, 'category', '') or '')
            name = _quantity_name(column)
            if category == column_category or category in name:
                return name
    return None


def _plot_label(quantity_name: str) -> str:
    if 'distribution' in quantity_name:
        return 'PSD curve'
    return _title_from_identifier(quantity_name)


def _plot_title(quantity_name: str) -> str:
    if 'distribution' in quantity_name:
        return 'Particle size distribution'
    return _title_from_identifier(quantity_name)


def _axis_title(quantity_name: str, unit: str | None) -> str:
    title = _title_from_identifier(quantity_name)
    return f'{title} / {unit}' if unit else title


def _title_from_identifier(identifier: str) -> str:
    text = re.sub(r'(?<!^)(?=[A-Z])', ' ', str(identifier)).replace('_', ' ')
    return re.sub(r'\s+', ' ', text).strip().title()


def _dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
