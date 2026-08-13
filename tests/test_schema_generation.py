from pathlib import Path

import pandas as pd
import yaml

from nomad_auto_upload_tables.parsers.tabular_guess import TabularGuessParser
from nomad_auto_upload_tables.schema_generation import build_generated_artifacts, build_results_dict, dump_review_yaml
from nomad_auto_upload_tables.schema_packages.tabular_guess import TabularGuess

DATA_DIR = Path(__file__).parent / 'data'


def test_pandas_comment_option_blanks_the_entire_row_not_just_the_matching_cell(tmp_path):
    """Documents *why* generated schemas must not set parsing_options.comment.

    This isn't specific to our code - it's pandas' own `comment=` semantics,
    confirmed here so a future re-addition of `comment: '#'` (e.g. to support
    literal comment-header lines in a CSV) fails this test immediately rather
    than silently corrupting any table where '#' appears anywhere, in any
    column, not just the one being read.
    """
    xlsx = tmp_path / 'demo.xlsx'
    pd.DataFrame({
        'sample': ['s1', 's2', '#s3', 's4'],
        'repeat_unit': ['[*]CC([*])(F)F', '[*]CC([*])(F)F', '[*]CCCCCCCCCCCNC([*])=C', '[*]CCCCCCCCCCCNC([*])=C'],
    }).to_excel(xlsx, index=False)

    df = pd.read_excel(xlsx, comment='#')

    # 's3' starts with '#' - not in repeat_unit at all - yet the whole row 2
    # (every column) comes back NaN, not just the 'sample' cell.
    assert df['sample'].isna().tolist() == [False, False, True, False]
    assert df['repeat_unit'].isna().tolist() == [False, False, True, False]


class _Context:
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


class _Archive:
    def __init__(self, raw_dir, data=None):
        self.data = data
        self.m_context = _Context(raw_dir)
        self.metadata = None


def _parse_review_from_csv(tmp_path, filename):
    raw_file = tmp_path / filename
    raw_file.write_bytes((DATA_DIR / filename).read_bytes())
    archive = _Archive(tmp_path)
    TabularGuessParser().parse(str(raw_file), archive)
    review_file = tmp_path / 'generated_reviews' / f'{Path(filename).stem}_review.archive.yaml'
    assert review_file.exists()
    review = yaml.safe_load(review_file.read_text())
    entry = TabularGuess.m_from_dict(review['data'])
    return archive, entry, review


def test_generated_schema_contains_native_nomad_tabular_shape(tmp_path):
    _, entry, _ = _parse_review_from_csv(tmp_path, 'sample.csv')
    entry.confirm_schema = True
    artifacts = build_generated_artifacts(entry)

    schema = yaml.safe_load(artifacts.schema_yaml)
    generated_entry = yaml.safe_load(artifacts.entry_yaml)
    section = schema['definitions']['sections'][artifacts.section_name]
    quantities = section['quantities']

    assert 'nomad.datamodel.data.EntryData' in section['base_sections']
    assert 'nomad.parsing.tabular.TableData' in section['base_sections']
    assert 'nomad.datamodel.metainfo.plot.PlotSection' in section['base_sections']
    assert 'nomad.datamodel.metainfo.eln.ElnBaseSection' in section['base_sections']
    assert quantities['tags']['default'] == ['nomad_auto_upload_tables']
    assert 'tags' in section['m_annotations']['eln']['hide']
    assert quantities['data_file']['m_annotations']['browser']['adaptor'] == 'RawFileAdaptor'
    assert quantities['data_file']['m_annotations']['eln']['component'] == 'FileEditQuantity'
    mapping = quantities['data_file']['m_annotations']['tabular_parser']['mapping_options'][0]
    assert mapping == {'mapping_mode': 'column', 'file_mode': 'current_entry', 'sections': ['#root']}
    # No comment character configured: pandas' `comment` handling blanks an
    # entire row (across every column) if any cell anywhere in that row
    # starts with the comment character - confirmed empirically, not just
    # theoretical. A hardcoded '#' silently turned genuine data (SMILES
    # nitrile/triple-bond "C#N", hex colors, "Batch #3" IDs, ...) into NaN
    # for reasons that had nothing to do with the source file being messy.
    assert 'parsing_options' not in quantities['data_file']['m_annotations']['tabular_parser']
    assert quantities['temperature']['shape'] == ['*']
    assert quantities['temperature']['type'] == 'np.float64'
    assert quantities['temperature']['unit'] == 'K'
    assert quantities['temperature']['m_annotations']['tabular']['name'] == 'Temperature (K)'
    assert generated_entry['data']['m_def'] == f'../uploads/archive/mainfile/{artifacts.schema_file}#/definitions/sections/{artifacts.section_name}'
    assert generated_entry['data']['data_file'] == 'sample.csv'
    assert generated_entry['data']['fill_archive_from_datafile'] is True


def test_all_combination_plots_covers_every_numeric_pair_histogram_and_heatmap(tmp_path):
    _, entry, _ = _parse_review_from_csv(tmp_path, 'sample.csv')
    # enable_all_combination_plots already defaults to True; set explicitly for clarity.
    entry.enable_all_combination_plots = True

    schema = yaml.safe_load(build_generated_artifacts(entry).schema_yaml)
    section = next(iter(schema['definitions']['sections'].values()))
    plots = section['m_annotations']['plotly_graph_object']
    labels = {plot['label'] for plot in plots}
    types = [plot['data']['type'] for plot in plots]

    # sample.csv: temperature/pressure are the only numeric columns.
    # 1 scatter pair + 2 histograms (one per numeric column) + 0 heatmaps (need 3 numeric) = 3.
    assert len(plots) == 3
    assert 'Pressure vs Temperature' in labels
    assert types.count('scatter') == 1
    assert types.count('histogram') == 2
    assert [plot['index'] for plot in plots] == list(range(len(plots)))
    # All open by default: otherwise the Overview plot picker hides every
    # figure but the first, forcing a click per plot to see the rest.
    assert all(plot['open'] is True for plot in plots)


def test_all_combination_plots_generates_heatmaps_for_numeric_triples(tmp_path):
    _, entry, _ = _parse_review_from_csv(tmp_path, 'psd_curve.csv')
    entry.enable_all_combination_plots = True

    schema = yaml.safe_load(build_generated_artifacts(entry).schema_yaml)
    section = next(iter(schema['definitions']['sections'].values()))
    plots = section['m_annotations']['plotly_graph_object']
    types = [plot['data']['type'] for plot in plots]

    # psd_curve.csv has 3 numeric columns: C(3,2)=3 scatter, 3 histograms, C(3,3)=1 heatmap.
    assert types.count('scatter') == 3
    assert types.count('histogram') == 3
    assert types.count('heatmap') == 1


def test_all_combination_plots_overrides_the_single_plot_checkboxes(tmp_path):
    _, entry, _ = _parse_review_from_csv(tmp_path, 'sample.csv')
    entry.enable_all_combination_plots = True
    entry.enable_histogram = True
    entry.plot_columns = 'temperature'

    schema = yaml.safe_load(build_generated_artifacts(entry).schema_yaml)
    section = next(iter(schema['definitions']['sections'].values()))
    plots = section['m_annotations']['plotly_graph_object']

    # Single-plot mode with this config would produce exactly one histogram
    # of 'temperature'; combination mode's fuller default set wins instead.
    assert len(plots) == 3


def test_all_combination_plots_is_capped_for_wide_tables(tmp_path):
    _, entry, _ = _parse_review_from_csv(tmp_path, 'sample.csv')
    entry.enable_all_combination_plots = True
    extra_columns = []
    for i in range(10):
        column = type(entry.columns[0])(**{
            key: getattr(entry.columns[1], key) for key in ('header', 'guessed_type', 'guessed_unit', 'category', 'include')
        })
        column.header = f'Extra {i}'
        column.guessed_name = f'extra_{i}'
        extra_columns.append(column)
    entry.columns = list(entry.columns) + extra_columns

    schema = yaml.safe_load(build_generated_artifacts(entry).schema_yaml)
    section = next(iter(schema['definitions']['sections'].values()))
    plots = section['m_annotations']['plotly_graph_object']

    assert len(plots) == 40


def test_generated_schema_excludes_columns_with_include_false(tmp_path):
    _, entry, _ = _parse_review_from_csv(tmp_path, 'sample.csv')
    by_header = {column.header: column for column in entry.columns}
    by_header['Notes'].include = False

    schema = yaml.safe_load(build_generated_artifacts(entry).schema_yaml)
    quantities = next(iter(schema['definitions']['sections'].values()))['quantities']

    assert 'notes' not in quantities
    assert 'sample_id' in quantities


def test_psd_curve_schema_matches_reference_structure(tmp_path):
    _, entry, _ = _parse_review_from_csv(tmp_path, 'psd_curve.csv')
    entry.generated_section_name = 'ParticleSizeDistribution'
    entry.enable_all_combination_plots = False
    artifacts = build_generated_artifacts(entry)

    generated = yaml.safe_load(artifacts.schema_yaml)
    reference = yaml.safe_load((DATA_DIR / 'particle_size_schema.archive.yaml').read_text())
    section = generated['definitions']['sections']['ParticleSizeDistribution']
    reference_section = reference['definitions']['sections']['ParticleSizeDistribution']
    quantities = section['quantities']

    assert section['base_sections'] == reference_section['base_sections']
    assert 'plotly_graph_object' in section['m_annotations']
    plot = section['m_annotations']['plotly_graph_object'][0]
    assert plot['data']['x'] == '#particle_diameter'
    assert plot['data']['y'] == '#volume_distribution'
    assert plot['data']['type'] == 'scatter'
    assert plot['data']['mode'] == 'lines+markers'
    assert quantities['particle_diameter']['type'] == 'np.float64'
    assert quantities['particle_diameter']['shape'] == ['*']
    assert quantities['particle_diameter']['unit'] == 'micrometer'
    assert quantities['volume_distribution']['unit'] == 'percent'
    assert quantities['undersize_distribution']['unit'] == 'percent'
    assert quantities['data_file']['m_annotations']['tabular_parser']['mapping_options'][0]['mapping_mode'] == 'column'


def test_generated_schema_supports_multiple_enabled_plots(tmp_path):
    _, entry, _ = _parse_review_from_csv(tmp_path, 'psd_curve.csv')
    entry.generated_section_name = 'ParticleSizeDistribution'
    entry.enable_all_combination_plots = False
    entry.enable_histogram = True
    entry.enable_violin = True
    entry.enable_area = True
    entry.enable_colored_scatter = True
    entry.plot_columns = 'particle_diameter, volume_distribution, undersize_distribution'

    schema = yaml.safe_load(build_generated_artifacts(entry).schema_yaml)
    section = schema['definitions']['sections']['ParticleSizeDistribution']
    plots = section['m_annotations']['plotly_graph_object']

    assert 'plotly_subplots' not in section['m_annotations']
    assert [plot['index'] for plot in plots] == [0, 1, 2, 3, 4]
    # All open by default: otherwise the Overview plot picker hides every
    # figure but the first, forcing a click per plot to see the rest.
    assert all(plot['open'] is True for plot in plots)
    assert plots[0]['data']['type'] == 'scatter'
    assert plots[1]['data']['fill'] == 'tozeroy'
    assert plots[2]['data']['type'] == 'histogram'
    assert plots[3]['data']['type'] == 'violin'
    assert plots[3]['data']['y'] == '#volume_distribution'
    assert plots[4]['data']['marker']['color'] == '#undersize_distribution'


def test_xlsx_generated_schema_uses_sheet_prefix_and_nomad_safe_units():
    entry = TabularGuess(
        data_file='zellstoff_daten.xlsx',
        sheet_name='Versuchsdaten',
        generated_section_name='ZellstoffDaten',
        plot_columns='length, mass_temperature',
        columns=[
            {
                'header': 'Massentemperatur  ',
                'guessed_name': 'mass_temperature',
                'guessed_type': 'integer',
                'guessed_unit': 'degC',
                'category': 'temperature',
            },
            {
                'header': 'Lochdurchsatz \n[cm³/min]',
                'guessed_name': 'hole_flow_rate',
                'guessed_type': 'float',
                'guessed_unit': 'cm^3/min',
                'category': 'process_parameter',
            },
            {
                'header': 'Düsengeometrie\nLoch / Durchmesser ',
                'guessed_name': 'nozzle_geometry',
                'guessed_type': 'string',
                'guessed_unit': '',
                'category': 'process_parameter',
            },
            {
                'header': 'Suction speed',
                'guessed_name': 'suction_speed',
                'guessed_type': 'float',
                'guessed_unit': 'm/min',
                'category': 'process_parameter',
            },
            {
                'header': 'Titer [dtex]',
                'guessed_name': 'titer',
                'guessed_type': 'float',
                'guessed_unit': 'dtex',
                'category': 'measurement_result',
            },
            {
                'header': 'Tenacity\n [cN/tex]',
                'guessed_name': 'tenacity',
                'guessed_type': 'float',
                'guessed_unit': 'cN/tex',
                'category': 'measurement_result',
            },
        ],
    )

    schema = yaml.safe_load(build_generated_artifacts(entry).schema_yaml)
    quantities = schema['definitions']['sections']['ZellstoffDaten']['quantities']

    assert quantities['mass_temperature']['m_annotations']['tabular']['name'] == 'Versuchsdaten/Massentemperatur'
    assert 'm_annotations' not in quantities['hole_flow_rate']
    assert quantities['hole_flow_rate']['unit'] == 'cm^3/minute'
    assert quantities['suction_speed']['m_annotations']['tabular']['name'] == 'Versuchsdaten/Suction speed'
    assert quantities['suction_speed']['unit'] == 'm/minute'
    assert 'm_annotations' not in quantities['nozzle_geometry']
    assert 'not auto-imported' in quantities['nozzle_geometry']['description']
    assert 'unit' not in quantities['titer']
    assert 'unit' not in quantities['tenacity']


def test_generated_entry_contains_nomad_results_material_and_method(tmp_path):
    _, entry, _ = _parse_review_from_csv(tmp_path, 'sample.csv')
    entry.enable_results_material = True
    entry.material_formula = 'K2Zn2BiSe4'
    entry.material_name = 'K Zn Bi Se test material'
    entry.enable_results_method = True
    entry.method_name = 'XRD'
    entry.workflow_name = 'Tabular import'

    generated_entry = yaml.safe_load(build_generated_artifacts(entry).entry_yaml)
    material = generated_entry['results']['material']
    method = generated_entry['results']['method']

    assert material['material_name'] == 'K Zn Bi Se test material'
    assert material['elements'] == ['Bi', 'K', 'Se', 'Zn']
    assert material['chemical_formula_descriptive'] == 'K2Zn2BiSe4'
    assert material['chemical_formula_reduced'] == 'BiK2Se4Zn2'
    assert material['chemical_formula_hill'] == 'BiK2Se4Zn2'
    assert material['chemical_formula_iupac'] == 'K2Zn2BiSe4'
    assert material['chemical_formula_anonymous'] == 'A4B2C2D'
    assert {item['element'] for item in material['elemental_composition']} == {'Bi', 'K', 'Se', 'Zn'}
    assert 'structural_type' not in material
    assert 'dimensionality' not in material
    assert method == {'method_name': 'XRD', 'workflow_name': 'Tabular import'}




def test_invalid_results_method_name_is_skipped_but_workflow_kept():
    results = build_results_dict(
        {
            'enable_results_method': True,
            'method_name': 'Hot Pressing / Reaction Bonding Sintering',
            'workflow_name': 'SiC Composite Consolidation Workflow',
        }
    )

    assert results['method'] == {'workflow_name': 'SiC Composite Consolidation Workflow'}

def test_invalid_material_formula_is_skipped():
    results = build_results_dict(
        {
            'enable_results_material': True,
            'material_formula': 'not a formula',
            'enable_results_method': True,
            'method_name': 'XRD',
        }
    )

    assert 'material' not in results
    assert results['method'] == {'method_name': 'XRD'}


def test_review_defaults_prefill_single_formula_and_method():
    review = yaml.safe_load(
        dump_review_yaml(
            data_file='materials.csv',
            sheet_name=None,
            n_rows=3,
            ai_assisted=False,
            columns=[
                {
                    'header': 'Chemical formula',
                    'sample_values': 'K2Zn2BiSe4',
                    'n_rows': 3,
                    'n_missing': 0,
                    'confidence': 0.9,
                    'guessed_name': 'chemical_formula',
                    'guessed_type': 'string',
                    'guessed_unit': '',
                    'category': 'composition',
                },
                {
                    'header': 'Measurement method',
                    'sample_values': 'XRD',
                    'n_rows': 3,
                    'n_missing': 0,
                    'confidence': 0.8,
                    'guessed_name': 'measurement_method',
                    'guessed_type': 'string',
                    'guessed_unit': '',
                    'category': 'measurement_result',
                },
            ],
        )
    )

    data = review['data']
    assert data['enable_results_material'] is True
    assert data['material_formula'] == 'K2Zn2BiSe4'
    assert data['enable_results_method'] is True
    assert data['method_name'] == 'XRD'
    assert data['structural_type'] == ''
    assert data['dimensionality'] == ''


def test_review_defaults_extract_formula_from_material_label():
    review = yaml.safe_load(
        dump_review_yaml(
            data_file='materials.csv',
            sheet_name=None,
            n_rows=3,
            ai_assisted=False,
            columns=[
                {
                    'header': 'Material',
                    'sample_values': 'al2o3_based',
                    'n_rows': 3,
                    'n_missing': 0,
                    'confidence': 0.9,
                    'guessed_name': 'material',
                    'guessed_type': 'string',
                    'guessed_unit': '',
                    'category': 'composition',
                },
            ],
        )
    )

    data = review['data']
    assert data['enable_results_material'] is True
    assert data['material_formula'] == 'Al2O3'


def test_results_material_extracts_formula_from_formula_like_label():
    results = build_results_dict(
        {
            'enable_results_material': True,
            'material_formula': 'al2o3_based',
        }
    )

    assert results['material']['elements'] == ['Al', 'O']
    assert results['material']['chemical_formula_descriptive'] == 'Al2O3'


def test_review_defaults_leave_multiple_formulas_blank():
    review = yaml.safe_load(
        dump_review_yaml(
            data_file='materials.csv',
            sheet_name=None,
            n_rows=2,
            ai_assisted=False,
            columns=[
                {
                    'header': 'Formula',
                    'sample_values': 'NaCl, KCl',
                    'n_rows': 2,
                    'n_missing': 0,
                    'confidence': 0.9,
                    'guessed_name': 'formula',
                    'guessed_type': 'string',
                    'guessed_unit': '',
                    'category': 'composition',
                }
            ],
        )
    )

    assert review['data']['enable_results_material'] is False
    assert review['data']['material_formula'] == ''

def test_invalid_enabled_plots_are_skipped(tmp_path):
    _, entry, _ = _parse_review_from_csv(tmp_path, 'sample.csv')
    entry.enable_all_combination_plots = False
    entry.enable_scatter_3d = True
    entry.enable_heatmap = True
    entry.plot_columns = 'temperature, pressure'

    schema = yaml.safe_load(build_generated_artifacts(entry).schema_yaml)
    section = next(iter(schema['definitions']['sections'].values()))
    plots = section['m_annotations']['plotly_graph_object']

    assert len(plots) == 1
    assert plots[0]['data']['type'] == 'scatter'
