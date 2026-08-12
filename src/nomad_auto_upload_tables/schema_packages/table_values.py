"""A fixed, plugin-defined companion schema for confirmed tabular entries.

The per-upload generated schema (`schema_generation.py`) creates a *new*
Python section class for every confirmed table - which is exactly why its
quantities (`pressure`, `temperature`, ...) can never be selected in a NOMAD
Explore dashboard `WidgetScatterPlot`: NOMAD only registers quantities from
schema *packages* (installed plugin entry points, see
`reload_quantities_dynamic` in `nomad.metainfo.elasticsearch_extension`) as
searchable/widget-bindable fields. Ad-hoc per-upload YAML schemas never enter
that registry, no matter how they're configured.

`TableValue`/`TableValues` are defined once, here, as a normal plugin schema
package - so unlike the per-upload schema, their quantities *are* stable,
searchable, and widget-bindable across every upload. A confirmed table's
values are additionally written out as `TableValue` entries (alongside, not
instead of, the per-upload native schema/entry) in *long format*: one
`TableValue` per (row, column), not one array-valued `TableValue` per
column. That's not a style choice - NOMAD only registers *scalar* quantities
(shape == []) as dynamic search quantities; an array-shaped quantity is
invisible to Explore dashboard widgets no matter how it's referenced
(confirmed directly against
`nomad.metainfo.elasticsearch_extension.create_dynamic_quantity_annotation`,
which unconditionally returns `None` when `quantity_def.shape != []`).

Each `TableValue` has a `property_name` naming the column (e.g. "pressure").
A dashboard widget can plot across every upload that happens to have a
matching `property_name`, using NOMAD's dynamic-quantity naming
(`data.<path>#<qualified class name>`) with a JMESPath filter, e.g.:

    x: {search_quantity: "data.values[?property_name=='temperature'].numeric_value#nomad_auto_upload_tables.schema_packages.table_values.TableValues"}
    y: {search_quantity: "data.values[?property_name=='pressure'].numeric_value#nomad_auto_upload_tables.schema_packages.table_values.TableValues"}
"""

from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.datamodel.metainfo.eln import ElnBaseSection
from nomad.metainfo import MEnum, Quantity, Section, SchemaPackage, SubSection

from nomad_auto_upload_tables.guessing import CATEGORIES
from nomad_auto_upload_tables.schema_generation import ELN_TAG

m_package = SchemaPackage()

# Same marker tag the per-upload generated schema carries (schema_generation.ELN_TAG),
# so both land in the "Tabular Data" Explore app's results.eln.tags filter.
_HIDDEN_ELN_FIELDS = ['name', 'datetime', 'lab_id', 'description', 'tags']


class TableValue(ArchiveSection):
    """One column's value for one row of a confirmed table, under a fixed
    property_name so it can be found and plotted across every upload. All
    value quantities are scalars (see module docstring for why)."""

    property_name = Quantity(
        type=str,
        description='Guessed quantity name for this column (e.g. "pressure"), matching the per-upload generated schema.',
    )
    category = Quantity(
        type=MEnum(CATEGORIES),
        description='Semantic category guessed for this column.',
    )
    unit = Quantity(
        type=str,
        description='Pint-compatible unit string for numeric_value, if any.',
    )
    source_row = Quantity(
        type=int,
        description='One-based source table row number this value came from.',
    )
    numeric_value = Quantity(
        type=float,
        description='This value, for float/integer columns.',
    )
    string_value = Quantity(
        type=str,
        description='This value, for string/boolean/datetime columns.',
    )


class TableValues(ElnBaseSection, EntryData):
    """Fixed-shape companion entry generated alongside a confirmed table's
    native per-upload schema/entry, so its columns are searchable and
    widget-bindable across uploads (see module docstring)."""

    m_def = Section(a_eln=ELNAnnotation(hide=_HIDDEN_ELN_FIELDS))

    source_file = Quantity(
        type=str,
        description='The confirmed table this entry\'s values were read from.',
    )
    tags = Quantity(
        type=str,
        shape=['*'],
        default=[ELN_TAG],
        description='Fixed marker tag copied into results.eln.tags by ElnBaseSection, used by the "Tabular Data" Explore app.',
    )
    values = SubSection(section=TableValue.m_def, repeats=True)


m_package.__init_metainfo__()
