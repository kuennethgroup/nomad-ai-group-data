from pathlib import Path

import yaml

from nomad.utils import generate_entry_id

from nomad_auto_upload_tables.parsers.tabular_guess import TabularGuessParser
from nomad_auto_upload_tables.schema_packages.tabular_guess import GuessedColumn, TabularGuess

DATA_DIR = Path(__file__).parent / 'data'


class FakeMetadata:
    def __init__(self, mainfile, upload_id='test-upload'):
        self.mainfile = mainfile
        self.upload_id = upload_id


class WritableFakeContext:
    def __init__(self, raw_dir):
        self.raw_dir = Path(raw_dir)
        self.processed = []

    def raw_path(self):
        return str(self.raw_dir)

    def raw_path_exists(self, path):
        return (self.raw_dir / path).exists()

    def raw_file(self, path, mode='rb', *args, **kwargs):
        target = self.raw_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        return open(target, mode)

    def process_updated_raw_file(self, path, allow_modify=False):
        self.processed.append((path, allow_modify))


class WritableFakeArchive:
    def __init__(self, raw_dir, data=None, mainfile=None, upload_id='test-upload'):
        self.data = data
        self.m_context = WritableFakeContext(raw_dir)
        self.metadata = FakeMetadata(mainfile, upload_id=upload_id) if mainfile else None


def test_parser_creates_review_archive_and_keeps_source_csv_unchanged(tmp_path):
    raw_csv = tmp_path / 'sample.csv'
    original = (DATA_DIR / 'sample.csv').read_bytes()
    raw_csv.write_bytes(original)
    archive = WritableFakeArchive(tmp_path, mainfile='sample.csv')

    TabularGuessParser().parse(str(raw_csv), archive)

    review_file = tmp_path / 'generated_reviews' / 'sample_review.archive.yaml'
    assert archive.data is None
    assert raw_csv.read_bytes() == original
    assert review_file.exists()
    assert archive.m_context.processed == [('generated_reviews/sample_review.archive.yaml', True)]

    review = yaml.safe_load(review_file.read_text())
    assert review['data']['m_def'] == 'nomad_auto_upload_tables.schema_packages.tabular_guess.TabularGuess'
    assert review['data']['data_file'] == 'sample.csv'
    assert review['data']['generated_schema_file'] == 'generated_schemas/sample_schema.archive.yaml'
    assert review['data']['generated_entry_file'] == 'generated_entries/sample_entry.archive.yaml'
    assert review['data']['enable_xy_scatter'] is True
    assert review['data']['enable_xy_line'] is False
    assert review['data']['enable_area'] is False
    assert 'enable_subplots_summary' not in review['data']
    assert 'enable_parallel_coordinates' not in review['data']
    assert review['data']['plot_label'] == 'Pressure'
    assert review['data']['plot_columns'] == 'temperature, pressure'
    assert {column['header'] for column in review['data']['columns']} >= {'Sample ID', 'Temperature (K)'}


def test_confirmed_review_generates_schema_and_entry_files(tmp_path):
    raw_csv = tmp_path / 'sample.csv'
    raw_csv.write_bytes((DATA_DIR / 'sample.csv').read_bytes())
    archive = WritableFakeArchive(tmp_path, mainfile='sample.csv')
    parser = TabularGuessParser()
    parser.parse(str(raw_csv), archive)

    review = yaml.safe_load((tmp_path / 'generated_reviews' / 'sample_review.archive.yaml').read_text())
    entry = TabularGuess.m_from_dict(review['data'])
    entry.confirm_schema = True
    archive.data = entry

    parser.after_normalization(archive)

    schema_file = tmp_path / 'generated_schemas' / 'sample_schema.archive.yaml'
    entry_file = tmp_path / 'generated_entries' / 'sample_entry.archive.yaml'
    assert schema_file.exists()
    assert entry_file.exists()
    processed_paths = [path for path, allow_modify in archive.m_context.processed]
    assert 'generated_schemas/sample_schema.archive.yaml' in processed_paths
    assert 'generated_entries/sample_entry.archive.yaml' in processed_paths

    generated_schema = yaml.safe_load(schema_file.read_text())
    generated_entry = yaml.safe_load(entry_file.read_text())
    schema_entry_id = generate_entry_id('test-upload', 'generated_schemas/sample_schema.archive.yaml')
    assert generated_entry['data']['m_def'] == (
        f'../uploads/test-upload/archive/{schema_entry_id}'
        '#/definitions/sections/Sample'
    )
    assert generated_entry['data']['data_file'] == 'sample.csv'
    assert generated_entry['data']['fill_archive_from_datafile'] is True

    quantities = generated_schema['definitions']['sections']['Sample']['quantities']
    assert quantities['temperature_mean']['type'] == 'np.float64'
    assert 'shape' not in quantities['temperature_mean']
    assert quantities['temperature_mean']['unit'] == 'K'
    assert generated_entry['data']['temperature_mean'] == 301.9
    assert generated_entry['data']['temperature_min'] == 295.0
    assert generated_entry['data']['temperature_max'] == 310.2
    assert 'search_temperature_mean' not in quantities
    assert 'search_temperature_mean' not in generated_entry['data']
    assert 'sample_id_2' not in quantities




def _confirmed_review_from_file(tmp_path, filename):
    raw_file = tmp_path / filename
    raw_file.write_bytes((DATA_DIR / filename).read_bytes())
    archive = WritableFakeArchive(tmp_path, mainfile=filename)
    parser = TabularGuessParser()
    parser.parse(str(raw_file), archive)
    review = yaml.safe_load((tmp_path / 'generated_reviews' / f'{Path(filename).stem}_review.archive.yaml').read_text())
    entry = TabularGuess.m_from_dict(review['data'])
    entry.confirm_schema = True
    archive.data = entry
    return parser, archive, entry


def test_confirmed_row_mode_generates_schema_and_row_entries(tmp_path):
    parser, archive, entry = _confirmed_review_from_file(tmp_path, 'sample.csv')
    entry.mapping_mode = 'row'

    parser.after_normalization(archive)

    schema_file = tmp_path / 'generated_schemas' / 'sample_row_schema.archive.yaml'
    row_dir = tmp_path / 'generated_row_entries' / 'sample'
    assert schema_file.exists()
    assert (row_dir / 'S001.archive.yaml').exists()
    assert (row_dir / 'S002.archive.yaml').exists()
    assert (row_dir / 'S003.archive.yaml').exists()

    processed_paths = [path for path, allow_modify in archive.m_context.processed]
    assert processed_paths.index('generated_schemas/sample_row_schema.archive.yaml') < processed_paths.index(
        'generated_row_entries/sample/S001.archive.yaml'
    )

    generated_schema = yaml.safe_load(schema_file.read_text())
    section = generated_schema['definitions']['sections']['Sample']
    quantities = section['quantities']
    assert section['base_sections'] == [
        'nomad.datamodel.metainfo.eln.ElnBaseSection',
        'nomad.datamodel.data.EntryData',
    ]
    assert section['more']['label_quantity'] == 'sample_id'
    assert quantities['source_file']['type'] == 'str'
    assert quantities['source_row']['type'] == 'np.int64'
    assert quantities['temperature']['type'] == 'np.float64'
    assert quantities['temperature']['unit'] == 'K'
    assert 'shape' not in quantities['temperature']
    assert 'data_file' not in quantities

    generated_entry = yaml.safe_load((row_dir / 'S001.archive.yaml').read_text())
    schema_entry_id = generate_entry_id('test-upload', 'generated_schemas/sample_row_schema.archive.yaml')
    assert generated_entry['data']['m_def'] == (
        f'../uploads/test-upload/archive/{schema_entry_id}'
        '#/definitions/sections/Sample'
    )
    assert generated_entry['metadata']['entry_name'] == 'S001'
    assert generated_entry['data']['source_file'] == 'sample.csv'
    assert generated_entry['data']['source_row'] == 1
    assert generated_entry['data']['sample_id'] == 'S001'
    assert generated_entry['data']['temperature'] == 300.5
    assert generated_entry['data']['pressure'] == 101325

    generated_entry = yaml.safe_load((row_dir / 'S002.archive.yaml').read_text())
    assert 'notes' not in generated_entry['data']

    table_values_file = tmp_path / 'generated_table_values' / 'sample_values.archive.yaml'
    assert table_values_file.exists()
    table_values = yaml.safe_load(table_values_file.read_text())
    assert table_values['data']['m_def'] == 'nomad_auto_upload_tables.schema_packages.table_values.TableValues'
    by_property = {v['property_name']: v for v in table_values['data']['values']}
    assert by_property['temperature']['numeric_value'] == [300.5, 310.2, 295.0]
    assert by_property['temperature']['unit'] == 'K'
    assert by_property['sample_id']['string_value'] == ['S001', 'S002', 'S003']


def test_confirmed_column_mode_generates_table_values_companion_entry(tmp_path):
    parser, archive, entry = _confirmed_review_from_file(tmp_path, 'sample.csv')

    parser.after_normalization(archive)

    table_values_file = tmp_path / 'generated_table_values' / 'sample_values.archive.yaml'
    assert table_values_file.exists()
    table_values = yaml.safe_load(table_values_file.read_text())
    data = table_values['data']
    assert data['m_def'] == 'nomad_auto_upload_tables.schema_packages.table_values.TableValues'
    assert data['source_file'] == 'sample.csv'
    assert data['name'] == 'Sample values'
    by_property = {v['property_name']: v for v in data['values']}
    assert by_property['temperature']['numeric_value'] == [300.5, 310.2, 295.0]
    assert by_property['temperature']['category'] == 'temperature'
    assert by_property['temperature']['unit'] == 'K'
    assert by_property['pressure']['numeric_value'] == [101325, 101300, 101400]
    assert by_property['sample_id']['string_value'] == ['S001', 'S002', 'S003']
    assert 'numeric_value' not in by_property['sample_id']


def test_row_mode_omits_invalid_values_and_deduplicates_row_ids(tmp_path):
    raw_csv = tmp_path / 'rows.csv'
    raw_csv.write_text('Sample ID,Value,Flag\nA,1.5,true\nA,bad,maybe\n,3.0,false\n')
    archive = WritableFakeArchive(tmp_path, mainfile='rows.csv')
    parser = TabularGuessParser()
    parser.parse(str(raw_csv), archive)
    review = yaml.safe_load((tmp_path / 'generated_reviews' / 'rows_review.archive.yaml').read_text())
    entry = TabularGuess.m_from_dict(review['data'])
    entry.confirm_schema = True
    entry.mapping_mode = 'row'
    by_header = {column.header: column for column in entry.columns}
    by_header['Value'].guessed_type = 'float'
    by_header['Flag'].guessed_type = 'boolean'
    archive.data = entry

    parser.after_normalization(archive)

    row_dir = tmp_path / 'generated_row_entries' / 'rows'
    assert (row_dir / 'A.archive.yaml').exists()
    assert (row_dir / 'A_2.archive.yaml').exists()
    assert (row_dir / 'row_0003.archive.yaml').exists()

    row1 = yaml.safe_load((row_dir / 'A.archive.yaml').read_text())['data']
    row2 = yaml.safe_load((row_dir / 'A_2.archive.yaml').read_text())['data']
    row3 = yaml.safe_load((row_dir / 'row_0003.archive.yaml').read_text())['data']
    assert row1['value'] == 1.5
    assert row1['flag'] is True
    assert 'value' not in row2
    assert 'flag' not in row2
    assert row3['value'] == 3.0
    assert row3['flag'] is False


def test_row_mode_does_not_clobber_files_without_force(tmp_path):
    parser, archive, entry = _confirmed_review_from_file(tmp_path, 'sample.csv')
    entry.mapping_mode = 'row'
    parser.after_normalization(archive)

    row_file = tmp_path / 'generated_row_entries' / 'sample' / 'S001.archive.yaml'
    row_file.write_text('sentinel: true\n')
    parser.after_normalization(archive)
    assert row_file.read_text() == 'sentinel: true\n'

    entry.force_regenerate = True
    parser.after_normalization(archive)
    assert 'source_row: 1' in row_file.read_text()



def test_row_mode_accepts_semicolon_tsv_and_xls_sources(tmp_path):
    cases = {
        'semicolon.csv': 'Sample ID;Temperature (K)\nS1;300.5\n',
        'table.tsv': 'Sample ID\tTemperature (K)\nS1\t300.5\n',
    }
    for filename, content in cases.items():
        source = tmp_path / filename
        source.write_text(content)
        archive = WritableFakeArchive(tmp_path, mainfile=filename)
        parser = TabularGuessParser()
        parser.parse(str(source), archive)
        review = yaml.safe_load((tmp_path / 'generated_reviews' / f'{Path(filename).stem}_review.archive.yaml').read_text())
        entry = TabularGuess.m_from_dict(review['data'])
        entry.confirm_schema = True
        entry.mapping_mode = 'row'
        archive.data = entry

        parser.after_normalization(archive)

        generated = tmp_path / 'generated_row_entries' / Path(filename).stem / 'S1.archive.yaml'
        assert generated.exists()
        assert yaml.safe_load(generated.read_text())['data']['temperature'] == 300.5

    xls_source = tmp_path / 'sample.xls'
    xls_source.write_bytes((DATA_DIR / 'sample.xlsx').read_bytes())
    archive = WritableFakeArchive(tmp_path, mainfile='sample.xls')
    parser = TabularGuessParser()
    parser.parse(str(xls_source), archive)
    review = yaml.safe_load((tmp_path / 'generated_reviews' / 'sample_review.archive.yaml').read_text())
    entry = TabularGuess.m_from_dict(review['data'])
    entry.confirm_schema = True
    entry.mapping_mode = 'row'
    archive.data = entry

    parser.after_normalization(archive)

    assert (tmp_path / 'generated_row_entries' / 'sample' / 'S001.archive.yaml').exists()


def test_xlsx_row_mode_generates_row_entries(tmp_path):
    parser, archive, entry = _confirmed_review_from_file(tmp_path, 'sample.xlsx')
    entry.mapping_mode = 'row'

    parser.after_normalization(archive)

    assert (tmp_path / 'generated_schemas' / 'sample_row_schema.archive.yaml').exists()
    assert (tmp_path / 'generated_row_entries' / 'sample' / 'S001.archive.yaml').exists()


def test_confirmed_review_does_not_clobber_generated_files_without_force(tmp_path):
    raw_csv = tmp_path / 'sample.csv'
    raw_csv.write_bytes((DATA_DIR / 'sample.csv').read_bytes())
    archive = WritableFakeArchive(tmp_path, mainfile='sample.csv')
    parser = TabularGuessParser()
    parser.parse(str(raw_csv), archive)
    review = yaml.safe_load((tmp_path / 'generated_reviews' / 'sample_review.archive.yaml').read_text())
    entry = TabularGuess.m_from_dict(review['data'])
    entry.confirm_schema = True
    archive.data = entry
    parser.after_normalization(archive)

    schema_file = tmp_path / 'generated_schemas' / 'sample_schema.archive.yaml'
    schema_file.write_text('sentinel: true\n')
    parser.after_normalization(archive)
    assert schema_file.read_text() == 'sentinel: true\n'

    entry.force_regenerate = True
    parser.after_normalization(archive)
    assert 'definitions:' in schema_file.read_text()


def test_reparsing_existing_review_entry_is_no_op_for_columns(tmp_path):
    entry = TabularGuess(
        data_file='sample.csv',
        confirm_schema=True,
        columns=[GuessedColumn(header='Sample ID', guessed_name='corrected_sample_id')],
    )
    archive = WritableFakeArchive(tmp_path, data=entry)

    TabularGuessParser().parse(str(DATA_DIR / 'sample.csv'), archive)

    assert archive.data is entry
    assert archive.data.columns[0].guessed_name == 'corrected_sample_id'


def test_parser_restores_tabular_guess_archive_json_files(tmp_path):
    archive_file = tmp_path / 'tabular_guess_test.archive.json'
    archive_file.write_text(
        '{"data":{"m_def":"nomad_auto_upload_tables.schema_packages.tabular_guess.TabularGuess",'
        '"data_file":"sample.csv","confirm_schema":true,'
        '"columns":[{"header":"Sample ID","guessed_name":"sample_id","include":true}]}}'
    )
    archive = WritableFakeArchive(tmp_path)

    TabularGuessParser().parse(str(archive_file), archive)

    assert isinstance(archive.data, TabularGuess)
    assert archive.data.data_file == 'sample.csv'
    assert archive.data.confirm_schema is True
    assert archive.data.columns[0].header == 'Sample ID'



def test_parser_prefills_plot_controls_from_ai_suggestion(monkeypatch, tmp_path):
    def fake_guess_with_ai(df, api_key, model, base_url, logger=None):
        return {
            'Sample ID': {
                'guessed_name': 'sample_id',
                'guessed_type': 'string',
                'guessed_unit': '',
                'category': 'sample_id',
                'confidence': 0.99,
            },
            'Temperature (K)': {
                'guessed_name': 'temperature',
                'guessed_type': 'float',
                'guessed_unit': 'K',
                'category': 'temperature',
                'confidence': 0.99,
            },
            'Pressure [Pa]': {
                'guessed_name': 'pressure',
                'guessed_type': 'float',
                'guessed_unit': 'Pa',
                'category': 'pressure',
                'confidence': 0.99,
            },
            'Yield (%)': {
                'guessed_name': 'yield',
                'guessed_type': 'float',
                'guessed_unit': '',
                'category': 'measurement_result',
                'confidence': 0.99,
            },
            '__plot_suggestions__': {
                'enabled_plots': ['xy_scatter', 'colored_scatter', 'parallel_coordinates', 'not_real'],
                'plot_label': 'AI overview',
                'plot_columns': ['temperature', 'pressure', 'yield'],
            },
        }

    monkeypatch.setattr('nomad_auto_upload_tables.ai_guessing.guess_with_ai', fake_guess_with_ai)
    raw_csv = tmp_path / 'sample.csv'
    # A genuinely all-numeric "Yield (%)" column, unlike sample.csv's text
    # "Notes" column - guess_columns() now validates AI numeric-type claims
    # against the real data (see _validated_numeric_type), so faking a float
    # guess for an actually-text column would just get downgraded to string.
    raw_csv.write_text(
        'Sample ID,Temperature (K),Pressure [Pa],Yield (%)\n'
        'S001,300.5,101325,92.1\n'
        'S002,310.2,101300,88.4\n'
        'S003,295.0,101400,95.0\n'
    )
    archive = WritableFakeArchive(tmp_path, mainfile='sample.csv')

    TabularGuessParser(api_key='sk-test', model='some-model').parse(str(raw_csv), archive)

    review = yaml.safe_load((tmp_path / 'generated_reviews' / 'sample_review.archive.yaml').read_text())
    assert review['data']['enable_xy_scatter'] is True
    assert review['data']['enable_colored_scatter'] is True
    assert review['data']['enable_histogram'] is False
    assert 'enable_parallel_coordinates' not in review['data']
    assert review['data']['plot_label'] == 'AI overview'
    assert review['data']['plot_columns'] == 'temperature, pressure, yield'


def test_parser_uses_ai_guess_when_configured(monkeypatch, tmp_path):
    def fake_guess_with_ai(df, api_key, model, base_url, logger=None):
        return {header: {
            'guessed_name': 'ai_name',
            'guessed_type': 'string',
            'guessed_unit': '',
            'category': 'measurement_result',
            'confidence': 0.99,
        } for header in df.columns.astype(str)}

    monkeypatch.setattr('nomad_auto_upload_tables.ai_guessing.guess_with_ai', fake_guess_with_ai)
    raw_csv = tmp_path / 'sample.csv'
    raw_csv.write_bytes((DATA_DIR / 'sample.csv').read_bytes())
    archive = WritableFakeArchive(tmp_path, mainfile='sample.csv')

    TabularGuessParser(api_key='sk-test', model='some-model').parse(str(raw_csv), archive)

    review = yaml.safe_load((tmp_path / 'generated_reviews' / 'sample_review.archive.yaml').read_text())
    assert review['data']['ai_assisted'] is True
    assert all(column['category'] == 'measurement_result' for column in review['data']['columns'])


def test_parser_ai_guesses_are_sanitized_before_columns_are_created(monkeypatch, tmp_path):
    def weird_guess_with_ai(df, api_key, model, base_url, logger=None):
        return {
            'Sample ID': {
                'guessed_name': '../Bad Name {m_def}',
                'guessed_type': 'not-a-real-type',
                'guessed_unit': 'not a unit',
                'category': 'not-a-real-category',
                'confidence': 42,
            },
            'Temperature (K)': {
                'guessed_name': '123 temperature',
                'guessed_type': 'float',
                'guessed_unit': 'K',
                'category': 'temperature',
                'confidence': 0.9,
            },
        }

    monkeypatch.setattr('nomad_auto_upload_tables.ai_guessing.guess_with_ai', weird_guess_with_ai)
    raw_csv = tmp_path / 'sample.csv'
    raw_csv.write_bytes((DATA_DIR / 'sample.csv').read_bytes())
    archive = WritableFakeArchive(tmp_path, mainfile='sample.csv')

    TabularGuessParser(api_key='sk-test', model='some-model').parse(str(raw_csv), archive)

    review = yaml.safe_load((tmp_path / 'generated_reviews' / 'sample_review.archive.yaml').read_text())
    by_header = {column['header']: column for column in review['data']['columns']}
    assert by_header['Sample ID']['guessed_name'] == 'bad_name_m_def'
    assert by_header['Sample ID']['guessed_type'] == 'string'
    assert by_header['Sample ID']['guessed_unit'] == ''
    assert by_header['Sample ID']['category'] == 'other'
    assert by_header['Sample ID']['confidence'] == 1.0
    assert by_header['Temperature (K)']['guessed_name'] == 'column_123_temperature'


def test_parser_falls_back_to_heuristics_when_ai_fails(monkeypatch, tmp_path):
    def failing_guess_with_ai(df, api_key, model, base_url, logger=None):
        return None

    monkeypatch.setattr('nomad_auto_upload_tables.ai_guessing.guess_with_ai', failing_guess_with_ai)
    raw_csv = tmp_path / 'sample.csv'
    raw_csv.write_bytes((DATA_DIR / 'sample.csv').read_bytes())
    archive = WritableFakeArchive(tmp_path, mainfile='sample.csv')

    TabularGuessParser(api_key='sk-test', model='some-model').parse(str(raw_csv), archive)

    review = yaml.safe_load((tmp_path / 'generated_reviews' / 'sample_review.archive.yaml').read_text())
    assert review['data']['ai_assisted'] is False
    by_header = {column['header']: column for column in review['data']['columns']}
    assert by_header['Temperature (K)']['category'] == 'temperature'
