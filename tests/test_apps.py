from nomad_auto_upload_tables.apps import tabular_guess_app
from nomad_auto_upload_tables.schema_generation import ELN_TAG


def test_tabular_guess_app_scopes_to_plugin_generated_entries():
    app = tabular_guess_app.app

    assert app.path == 'tabular-data'
    assert app.filters_locked == {'results.eln.tags': ELN_TAG}
    search_quantities = {column.search_quantity for column in app.columns}
    assert {'entry_name', 'upload_name', 'authors.name'} <= search_quantities


def test_tabular_guess_app_makes_dynamic_quantities_selectable_in_widgets():
    app = tabular_guess_app.app
    qualified_class = 'nomad_auto_upload_tables.schema_packages.table_values.TableValues'
    quantity = f'data.values.numeric_value#{qualified_class}'

    # NOMAD's widget "Search quantity" autocomplete only lists a dynamic
    # quantity (any quantity from a schema package) when it matches
    # search_quantities.include; the App default leaves include unset, which
    # excludes every dynamic quantity regardless of exclude. Without this,
    # our quantities are correctly registered and queryable, but every
    # widget editor still reports them as "is not available" to select.
    from fnmatch import fnmatch

    assert app.search_quantities is not None
    assert app.search_quantities.include
    assert any(fnmatch(quantity, pattern) for pattern in app.search_quantities.include)


def test_tabular_guess_app_dashboard_binds_to_stable_table_values_schema():
    app = tabular_guess_app.app
    qualified_class = 'nomad_auto_upload_tables.schema_packages.table_values.TableValues'

    assert len(app.dashboard.widgets) == 1
    widget = app.dashboard.widgets[0]
    # NOMAD only exposes schema-package quantities as data.<path>#<class> -
    # a bare "values.numeric_value" is never a valid search_quantity.
    assert widget.x.search_quantity == f"data.values[?property_name=='temperature'].numeric_value#{qualified_class}"
    assert widget.y.search_quantity == f"data.values[?property_name=='pressure'].numeric_value#{qualified_class}"
