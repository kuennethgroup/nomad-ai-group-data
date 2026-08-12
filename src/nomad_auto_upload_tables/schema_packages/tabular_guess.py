"""
Schema for the tabular schema-review workflow.

A :class:`TabularGuess` entry is created automatically for uploaded CSV/XLSX
source tables. It is only a review entry: users correct the guessed column
mapping, then tick ``confirm_schema`` to generate native NOMAD YAML schema and
entry archive files that use NOMAD's built-in tabular parser.
"""

from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation, ELNComponentEnum
from nomad.metainfo import MEnum, Quantity, SchemaPackage, SubSection

from nomad_auto_upload_tables.guessing import CATEGORIES, QUANTITY_TYPES

m_package = SchemaPackage()

MAPPING_MODES = ['column', 'row']

PLOT_CHECKBOXES = (
    'enable_xy_scatter',
    'enable_xy_line',
    'enable_area',
    'enable_bar',
    'enable_histogram',
    'enable_box',
    'enable_violin',
    'enable_heatmap',
    'enable_scatter_3d',
    'enable_colored_scatter',
)


class GuessedColumn(ArchiveSection):
    """One spreadsheet column together with the guessed and user-corrected
    semantic meaning, type, unit, and ontology-ish category."""

    header = Quantity(type=str, description='Original column header text.')
    sample_values = Quantity(
        type=str, description='A few example values from this column, for review.'
    )
    n_rows = Quantity(type=int, description='Number of non-empty cells in this column.')
    n_missing = Quantity(type=int, description='Number of empty/missing cells in this column.')
    confidence = Quantity(type=float, description='Heuristic/AI confidence in this guess (0-1).')

    guessed_name = Quantity(
        type=str,
        description='Generated quantity name for this column in the YAML schema.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    guessed_type = Quantity(
        type=MEnum(QUANTITY_TYPES),
        description='Generated NOMAD quantity type for this column.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )
    guessed_unit = Quantity(
        type=str,
        description='Pint-compatible unit string to use in the generated YAML schema, if any.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    category = Quantity(
        type=MEnum(CATEGORIES),
        description='Semantic category used for review and plot suggestions.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )
    include = Quantity(
        type=bool,
        default=True,
        description='Whether to include this column in the generated NOMAD schema.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity),
    )


class GuessedProperty(ArchiveSection):
    """Deprecated preview/debug shape from the early workflow."""

    name = Quantity(type=str)
    value = Quantity(type=str)
    unit = Quantity(type=str)
    category = Quantity(type=str)


class GuessedRow(ArchiveSection):
    """Deprecated preview/debug shape from the early workflow."""

    properties = SubSection(section=GuessedProperty.m_def, repeats=True)


class TabularGuess(EntryData):
    """Schema-review entry for an uploaded source table.

    This entry is not the final structured data. After confirmation, the plugin
    creates a YAML schema archive and a companion YAML data-entry archive. NOMAD's
    native tabular parser then imports this same source table into array
    quantities.
    """

    data_file = Quantity(
        type=str,
        description='The uploaded CSV/XLSX source table this schema review was guessed from.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.FileEditQuantity),
    )
    sheet_name = Quantity(type=str, description='Sheet name used, for multi-sheet workbooks.')
    n_rows = Quantity(type=int, description='Number of data rows detected in the source table.')
    ai_assisted = Quantity(
        type=bool,
        default=False,
        description=(
            'Whether the column guesses below came from the configured AI '
            'endpoint, as opposed to the local heuristic fallback.'
        ),
    )

    confirm_schema = Quantity(
        type=bool,
        default=False,
        description=(
            'This entry is only a review of the guessed schema. After confirmation, '
            'the plugin will create a YAML schema and a structured entry that imports '
            'this same table with NOMAD\'s native tabular parser.'
        ),
        a_eln=ELNAnnotation(
            component=ELNComponentEnum.BoolEditQuantity,
            label='Generate NOMAD schema and entry',
        ),
    )
    force_regenerate = Quantity(
        type=bool,
        default=False,
        description='Overwrite existing generated schema/entry files on the next save.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity),
    )
    generated_section_name = Quantity(
        type=str,
        description='Section name to define in the generated YAML schema.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    generated_schema_file = Quantity(
        type=str,
        description='Generated YAML schema archive path.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    generated_entry_file = Quantity(
        type=str,
        description='Generated YAML data-entry archive path.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity),
    )
    mapping_mode = Quantity(
        type=MEnum(MAPPING_MODES),
        default='column',
        description='Generation mode. Column mode creates one entry per table with array quantities; row mode creates one scalar entry per table row.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.EnumEditQuantity),
    )
    enable_xy_scatter = Quantity(
        type=bool,
        default=False,
        description='Generate a Plotly XY scatter plot from the first two plot columns.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='XY scatter plot'),
    )
    enable_xy_line = Quantity(
        type=bool,
        default=False,
        description='Generate a Plotly XY line plot from the first two plot columns.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='XY line plot'),
    )
    enable_area = Quantity(
        type=bool,
        default=False,
        description='Generate a Plotly area plot from the first two plot columns.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='Area plot'),
    )
    enable_bar = Quantity(
        type=bool,
        default=False,
        description='Generate a Plotly bar plot from the first two plot columns.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='Bar plot'),
    )
    enable_histogram = Quantity(
        type=bool,
        default=False,
        description='Generate Plotly histogram traces from the selected plot columns.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='Histogram'),
    )
    enable_box = Quantity(
        type=bool,
        default=False,
        description='Generate Plotly box traces from the selected plot columns.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='Box plot'),
    )
    enable_violin = Quantity(
        type=bool,
        default=False,
        description='Generate Plotly violin traces from the selected plot columns.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='Violin plot'),
    )
    enable_heatmap = Quantity(
        type=bool,
        default=False,
        description='Generate a Plotly heatmap from the first three plot columns.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='Heatmap'),
    )
    enable_scatter_3d = Quantity(
        type=bool,
        default=False,
        description='Generate a Plotly 3D scatter plot from the first three plot columns.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='3D scatter plot'),
    )
    enable_colored_scatter = Quantity(
        type=bool,
        default=False,
        description='Generate a Plotly scatter plot using the third plot column as color.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='Colored scatter plot'),
    )
    enable_all_combination_plots = Quantity(
        type=bool,
        default=False,
        description=(
            'Generate one scatter plot per pair of numeric columns, one bar chart per '
            'categorical-vs-numeric pair, and one standalone bar chart per numeric '
            'column, each as a separate figure you can switch between with the plot '
            'picker on the generated entry\'s Overview page. Overrides the plot type '
            'checkboxes and plot columns below, which configure a single plot instead.'
        ),
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='All combination plots'),
    )
    plot_label = Quantity(
        type=str,
        description='Shared base label for generated Plotly plots.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity, label='Plot label'),
    )
    plot_columns = Quantity(
        type=str,
        description='Comma-separated generated quantity names used by enabled plots, in order.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity, label='Plot columns'),
    )
    enable_results_material = Quantity(
        type=bool,
        default=False,
        description='Populate NOMAD results.material in the generated entry for formula/element search.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='Add results material'),
    )
    material_formula = Quantity(
        type=str,
        description='Entry-level chemical formula used to populate NOMAD results.material.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity, label='Material formula'),
    )
    material_name = Quantity(
        type=str,
        description='Optional entry-level material name for NOMAD results.material.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity, label='Material name'),
    )
    structural_type = Quantity(
        type=str,
        description='Optional NOMAD material structural type. Leave blank if unknown.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity, label='Structural type'),
    )
    dimensionality = Quantity(
        type=str,
        description='Optional NOMAD material dimensionality. Leave blank if unknown.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity, label='Dimensionality'),
    )
    enable_results_method = Quantity(
        type=bool,
        default=False,
        description='Populate basic NOMAD results.method metadata in the generated entry.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.BoolEditQuantity, label='Add results method'),
    )
    method_name = Quantity(
        type=str,
        description='Optional method name for NOMAD results.method.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity, label='Method name'),
    )
    workflow_name = Quantity(
        type=str,
        description='Optional workflow name for NOMAD results.method.',
        a_eln=ELNAnnotation(component=ELNComponentEnum.StringEditQuantity, label='Workflow name'),
    )

    columns = SubSection(section=GuessedColumn.m_def, repeats=True)
    rows = SubSection(section=GuessedRow.m_def, repeats=True)

    def normalize(self, archive, logger):
        super().normalize(archive, logger)

        if not (self.confirm_schema and self.columns and self.data_file):
            return

        from nomad_auto_upload_tables.schema_generation import build_generated_artifacts
        from nomad_auto_upload_tables.tabular_guess_build import write_generated_artifacts

        try:
            artifacts = build_generated_artifacts(self)
            write_generated_artifacts(self, archive, artifacts, logger=logger)
        except Exception as e:  # noqa: BLE001 - report to the user via the processing log
            logger.error('Failed to generate NOMAD schema and entry from confirmed tabular review', exc_info=e)


m_package.__init_metainfo__()
