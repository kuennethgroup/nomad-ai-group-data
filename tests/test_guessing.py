from pathlib import Path

import pandas as pd
import pytest

from nomad_auto_upload_tables.guessing import (
    ColumnGuess,
    clean_name,
    coerce_value,
    guess_category,
    guess_columns,
    guess_type,
    guess_unit,
    is_supported_table_file,
    is_uncertainty_header,
    link_uncertainty_columns,
    read_table,
)

DATA_DIR = Path(__file__).parent / 'data'


def test_read_table_csv():
    df, sheet_name = read_table(DATA_DIR / 'sample.csv')
    assert sheet_name is None
    assert list(df.columns) == [
        'Sample ID',
        'Temperature (K)',
        'Pressure [Pa]',
        'Synthesis Date',
        'Notes',
    ]
    assert len(df) == 3




def test_read_table_sniffs_semicolon_csv(tmp_path):
    path = tmp_path / 'sample.csv'
    path.write_text('Sample ID;Temperature (K);Pressure [Pa]\nS1;300.5;101325\nS2;310.0;100000\n')

    df, sheet_name = read_table(path)

    assert sheet_name is None
    assert list(df.columns) == ['Sample ID', 'Temperature (K)', 'Pressure [Pa]']
    assert df['Temperature (K)'].tolist() == [300.5, 310.0]


def test_read_table_accepts_tsv(tmp_path):
    path = tmp_path / 'sample.tsv'
    path.write_text('Sample ID\tTemperature (K)\tPressure [Pa]\nS1\t300.5\t101325\n')

    df, sheet_name = read_table(path)

    assert sheet_name is None
    assert list(df.columns) == ['Sample ID', 'Temperature (K)', 'Pressure [Pa]']
    assert len(df) == 1


def test_read_table_accepts_xls_extension(tmp_path):
    path = tmp_path / 'sample.xls'
    source, _ = read_table(DATA_DIR / 'sample.xlsx')
    source.to_excel(path, index=False)

    df, sheet_name = read_table(path)

    assert sheet_name == 'Sheet1'
    assert list(df.columns) == list(source.columns)
    assert len(df) == len(source)

def test_guess_unit_parses_parenthesized_and_bracketed_units():
    assert guess_unit('Temperature (K)') == 'K'
    assert guess_unit('Pressure [Pa]') == 'Pa'
    assert guess_unit('Notes') is None
    assert guess_unit('Made up unit (frobnicate)') is None


def test_guess_category_matches_keywords():
    assert guess_category('Sample ID')[0] == 'sample_id'
    assert guess_category('Temperature (K)')[0] == 'temperature'
    assert guess_category('Pressure [Pa]')[0] == 'pressure'
    category, confidence = guess_category('Some unrelated header')
    assert category == 'other'
    assert confidence < 0.5


def test_clean_name_strips_unit_and_snake_cases():
    assert clean_name('Temperature (K)') == 'temperature'
    assert clean_name('Pressure [Pa]') == 'pressure'
    assert clean_name('Sample ID') == 'sample_id'


def test_guess_type_for_numeric_and_string_columns():
    df, _ = read_table(DATA_DIR / 'sample.csv')
    assert guess_type(df['Temperature (K)']) == 'float'
    assert guess_type(df['Sample ID']) == 'string'


def test_guess_type_for_datetime_like_strings():
    df, _ = read_table(DATA_DIR / 'sample.csv')
    assert guess_type(df['Synthesis Date']) == 'datetime'


def test_read_table_xlsx_picks_up_sheet_name():
    df, sheet_name = read_table(DATA_DIR / 'sample.xlsx')
    assert sheet_name == 'Measurements'
    assert len(df) == 3


def test_guess_columns_end_to_end():
    df, _ = read_table(DATA_DIR / 'sample.csv')
    columns = {c.header: c for c in guess_columns(df)}

    temp = columns['Temperature (K)']
    assert temp.guessed_name == 'temperature'
    assert temp.guessed_type == 'float'
    assert temp.guessed_unit == 'K'
    assert temp.category == 'temperature'
    assert temp.n_missing == 0

    notes = columns['Notes']
    assert notes.n_missing == 1
    assert notes.category == 'other'


def test_coerce_value_handles_missing_and_types():
    assert coerce_value(float('nan'), 'float') is None
    assert coerce_value('3.5', 'float') == 3.5
    assert coerce_value('7', 'integer') == 7
    assert coerce_value('S001', 'string') == 'S001'


def test_guess_columns_handles_compound_units_and_padded_headers():
    df, _ = read_table(DATA_DIR / 'data_test.csv')
    columns = {c.header: c for c in guess_columns(df)}

    assert columns['Block A '].guessed_name == 'block_a'
    assert columns['Block A '].guessed_type == 'integer'

    start = columns['start [m/s]']
    assert start.guessed_unit == 'm/s'
    assert start.guessed_type == 'integer'

    delta = columns['delta [km]']
    assert delta.guessed_unit == 'km'
    assert delta.guessed_type == 'float'

    # A trailing fractional value pulls the whole column to float.
    assert columns['Block'].guessed_type == 'float'


def test_read_table_rejects_unsupported_files(tmp_path):
    archive_file = tmp_path / 'sample.archive.json'
    archive_file.write_text('{"data":{"m_def":"example"}}')

    assert is_supported_table_file(archive_file) is False
    with pytest.raises(ValueError, match='Unsupported table file extension'):
        read_table(archive_file)


def test_read_table_rejects_archive_content_even_with_csv_suffix(tmp_path):
    archive_file = tmp_path / 'sample.csv'
    archive_file.write_text('{"data":{"m_def":"nomad_auto_upload_tables.schema_packages.tabular_guess.TabularGuess","rows":[]}}')

    assert is_supported_table_file(archive_file) is True
    with pytest.raises(ValueError, match='appears to be a NOMAD archive'):
        read_table(archive_file)


def test_is_uncertainty_header_matches_common_markers():
    for header in [
        '+/-', '+-', '±', 'Error', 'error', 'Err.', 'Std Dev', 'std dev.',
        'StdErr', 'Uncertainty', 'Uncertainties', 'unc.', '± [MPa]', 'Error (Pa)',
    ]:
        assert is_uncertainty_header(header), header


def test_is_uncertainty_header_leaves_unrelated_headers_alone():
    for header in ['Error Code', 'Sample Error Log', 'Pressure [MPa]', 'Notes']:
        assert not is_uncertainty_header(header), header


def test_guess_columns_links_uncertainty_column_to_previous_column():
    df = pd.DataFrame({'Pressure [MPa]': [1.0, 2.0, 3.0], '+/-': [0.1, 0.2, 0.1]})
    columns = {c.header: c for c in guess_columns(df)}

    uncertainty = columns['+/-']
    assert uncertainty.guessed_name == 'pressure_uncertainty'
    assert uncertainty.guessed_unit == 'MPa'
    assert uncertainty.category == 'uncertainty'


def test_guess_columns_uncertainty_column_keeps_its_own_unit_if_present():
    df = pd.DataFrame({'Pressure [MPa]': [1.0, 2.0], 'Error [kPa]': [10.0, 20.0]})
    columns = {c.header: c for c in guess_columns(df)}

    assert columns['Error [kPa]'].guessed_unit == 'kPa'
    assert columns['Error [kPa]'].guessed_name == 'pressure_uncertainty'


def test_guess_columns_links_each_uncertainty_column_to_its_own_predecessor():
    df = pd.DataFrame({
        'Pressure [MPa]': [1.0],
        '+/-': [0.1],
        'Temperature [K]': [300.0],
        'Error': [1.0],
    })
    names = [c.guessed_name for c in guess_columns(df)]

    assert names == ['pressure', 'pressure_uncertainty', 'temperature', 'temperature_uncertainty']


def test_guess_columns_leading_uncertainty_column_is_left_alone():
    # No preceding column to attach to - must not crash or be relabeled.
    df = pd.DataFrame({'+/-': [0.1, 0.2]})
    columns = guess_columns(df)

    assert columns[0].category != 'uncertainty'


def test_link_uncertainty_columns_dedupes_name_collisions():
    columns = [
        ColumnGuess(
            header='Pressure [MPa]', guessed_name='pressure', guessed_type='float',
            guessed_unit='MPa', category='pressure', confidence=0.8,
            n_rows=3, n_missing=0, sample_values='1, 2, 3',
        ),
        ColumnGuess(
            header='+/-', guessed_name='column', guessed_type='float',
            guessed_unit='', category='other', confidence=0.2,
            n_rows=3, n_missing=0, sample_values='0.1',
        ),
        # A genuine, unrelated column that happens to already use the name our
        # linking pass would otherwise pick for the "+/-" column above.
        ColumnGuess(
            header='pressure_uncertainty', guessed_name='pressure_uncertainty', guessed_type='float',
            guessed_unit='MPa', category='other', confidence=0.2,
            n_rows=3, n_missing=0, sample_values='0.05',
        ),
    ]

    result = link_uncertainty_columns(columns)

    assert result[1].guessed_name == 'pressure_uncertainty_2'


def test_real_world_csv_fixtures_guess_expected_columns():
    expected = {
        'tabular_guess_test.csv': {
            'Temperature (K)': ('temperature', 'K'),
            'Pressure [Pa]': ('pressure', 'Pa'),
            'Mass (g)': ('mass', 'g'),
            'Time (s)': ('time', 's'),
            'Composition SiC wt%': ('composition', ''),
        },
        'psd_test.csv': {
            'Particle diameter (um)': ('length', 'um'),
            'Size distribution volume weighted (%)': ('mass', '%'),
            'Undersize volume weighted (%)': ('mass', '%'),
            'Measurement method': ('measurement_result', ''),
        },
        'messy_table_test.csv': {
            'specimen': ('sample_id', ''),
            'T_K': ('other', ''),
            'pres_pa': ('other', ''),
            'm_g': ('other', ''),
        },
    }

    for filename, columns_to_check in expected.items():
        df, sheet_name = read_table(DATA_DIR / filename)
        assert sheet_name is None
        columns = {c.header: c for c in guess_columns(df)}
        for header, (category, unit) in columns_to_check.items():
            assert columns[header].category == category
            assert columns[header].guessed_unit == unit
