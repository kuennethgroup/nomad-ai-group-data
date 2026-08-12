from nomad.config.models.plugins import SchemaPackageEntryPoint


class TabularGuessSchemaEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_auto_upload_tables.schema_packages.tabular_guess import m_package

        return m_package


tabular_guess_schema = TabularGuessSchemaEntryPoint(
    name='TabularGuessSchema',
    description=(
        'Schema for reviewing and correcting an automatically guessed table '
        'structure for uploaded Excel/CSV data.'
    ),
)


class TableValuesSchemaEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_auto_upload_tables.schema_packages.table_values import m_package

        return m_package


table_values_schema = TableValuesSchemaEntryPoint(
    name='TableValuesSchema',
    description=(
        'Fixed, plugin-defined companion schema for confirmed tabular entries, so '
        'their columns are searchable and widget-bindable across every upload - '
        'unlike each upload\'s own dynamically generated schema.'
    ),
)
