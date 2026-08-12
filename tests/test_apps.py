from nomad_auto_upload_tables.apps import tabular_guess_app
from nomad_auto_upload_tables.schema_generation import ELN_TAG


def test_tabular_guess_app_scopes_to_plugin_generated_entries():
    app = tabular_guess_app.app

    assert app.path == 'tabular-data'
    assert app.filters_locked == {'results.eln.tags': ELN_TAG}
    search_quantities = {column.search_quantity for column in app.columns}
    assert {'entry_name', 'upload_name', 'authors.name'} <= search_quantities


def test_tabular_guess_app_dashboard_binds_to_stable_table_values_schema():
    app = tabular_guess_app.app

    assert len(app.dashboard.widgets) == 1
    widget = app.dashboard.widgets[0]
    assert widget.x.search_quantity == "values[?property_name=='temperature'].numeric_value[]"
    assert widget.y.search_quantity == "values[?property_name=='pressure'].numeric_value[]"
