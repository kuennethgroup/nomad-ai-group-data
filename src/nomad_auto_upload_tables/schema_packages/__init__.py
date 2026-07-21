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


class CeramicTableDataSchemaEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_auto_upload_tables.schema_packages.ceramics import m_package

        return m_package


ceramic_table_data_schema = CeramicTableDataSchemaEntryPoint(
    name='CeramicTableDataSchema',
    description='Stable search quantities for generated ceramic table summaries.',
)
