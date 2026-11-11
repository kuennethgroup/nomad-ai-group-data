"""The classic ELN form and GUI v2 must expose the same review controls."""

import logging

import pytest
from nomad.datamodel.datamodel import EntryArchive

from nomad_auto_upload_tables.schema_generation import build_review_dict
from nomad_auto_upload_tables.schema_packages.tabular_guess import GuessedColumn, TabularGuess


REVIEW_FIELDS = [
    'data_file', 'confirm_schema', 'generated_section_name',
    'generated_schema_file', 'generated_entry_file', 'mapping_mode',
    'enable_all_combination_plots', 'enable_results_material',
    'material_formula', 'material_name', 'structural_type', 'dimensionality',
    'enable_results_method', 'method_name', 'workflow_name', 'columns',
]
COLUMN_FIELDS = ['guessed_name', 'guessed_type', 'guessed_unit', 'category', 'include']


@pytest.mark.parametrize('section, fields', [(TabularGuess, REVIEW_FIELDS), (GuessedColumn, COLUMN_FIELDS)])
def test_explicit_visibility_matches_classic_editable_fields(section, fields):
    annotation = section.m_def.m_get_annotations('eln')
    assert annotation.properties.visible.include == fields
    assert annotation.properties.order == fields
    editable_fields = {
        name for name, quantity in section.m_def.all_quantities.items()
        if quantity.m_annotations.get('eln')
        and quantity.m_get_annotations('eln').component
    }
    assert set(fields) == editable_fields | ({'columns'} if section is TabularGuess else set())


@pytest.mark.parametrize('section', [TabularGuess, GuessedColumn])
def test_boolean_editors_use_checkboxes(section):
    for quantity in section.m_def.all_quantities.values():
        annotation = quantity.m_get_annotations('eln')
        if annotation and annotation.component == 'BoolEditQuantity':
            assert annotation.props['variant'] == 'checkbox'


def test_normalization_materializes_defaults_in_legacy_review_without_overwriting_choices():
    entry = TabularGuess(columns=[GuessedColumn(), GuessedColumn(include=False)])
    archive = EntryArchive(data=entry)
    entry.normalize(archive, logging.getLogger(__name__))
    data = entry.m_to_dict()
    assert data['confirm_schema'] is True
    assert data['enable_all_combination_plots'] is True
    assert data['enable_results_material'] is False
    assert data['enable_results_method'] is False
    assert data['mapping_mode'] == 'column'
    assert data['columns'][0]['include'] is True
    assert data['columns'][1]['include'] is False


def test_normalization_preserves_explicit_false_and_row_mode():
    entry = TabularGuess(confirm_schema=False, enable_all_combination_plots=False, mapping_mode='row')
    entry.normalize(EntryArchive(data=entry), logging.getLogger(__name__))
    data = entry.m_to_dict()
    assert data['confirm_schema'] is False
    assert data['enable_all_combination_plots'] is False
    assert data['mapping_mode'] == 'row'


def test_new_review_files_include_generation_defaults():
    data = build_review_dict(data_file='test.csv', sheet_name=None, n_rows=0,
                             ai_assisted=False, columns=[])['data']
    for name in ('confirm_schema', 'force_regenerate', 'enable_all_combination_plots'):
        assert data[name] is True
