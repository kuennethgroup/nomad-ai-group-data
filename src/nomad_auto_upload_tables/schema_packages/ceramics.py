"""Fixed search bridge schema for common ceramic table summaries.

Generated per-upload YAML schemas remain the source of the imported table
shape. This plugin-level base section gives NOMAD a stable schema package
from which it can register Explore/search quantities for common scalar table
summaries.
"""
import numpy as np

from nomad.datamodel.data import EntryData
from nomad.metainfo import Quantity, SchemaPackage

m_package = SchemaPackage()

CERAMIC_TABLE_SUMMARY_COLUMNS = (
    'sintering_temperature_c',
    'secondary_content_wt_percent',
    'density_g_cm3',
    'relative_density_percent',
    'open_porosity_percent',
    'hardness_gpa',
    'youngs_modulus_gpa',
    'flexural_strength_mpa',
    'fracture_toughness_mpa_m05',
    'wear_rate_mm3_nm',
    'grain_size_um',
)


class CeramicTableData(EntryData):
    """Stable search bridge for common generated ceramic table summaries."""

    sintering_temperature_c_mean = Quantity(
        type=np.float64,
        description="Scalar mean summary for imported ceramic table column 'sintering_temperature_c'.",
    )
    sintering_temperature_c_min = Quantity(
        type=np.float64,
        description="Scalar min summary for imported ceramic table column 'sintering_temperature_c'.",
    )
    sintering_temperature_c_max = Quantity(
        type=np.float64,
        description="Scalar max summary for imported ceramic table column 'sintering_temperature_c'.",
    )

    secondary_content_wt_percent_mean = Quantity(
        type=np.float64,
        description="Scalar mean summary for imported ceramic table column 'secondary_content_wt_percent'.",
    )
    secondary_content_wt_percent_min = Quantity(
        type=np.float64,
        description="Scalar min summary for imported ceramic table column 'secondary_content_wt_percent'.",
    )
    secondary_content_wt_percent_max = Quantity(
        type=np.float64,
        description="Scalar max summary for imported ceramic table column 'secondary_content_wt_percent'.",
    )

    density_g_cm3_mean = Quantity(
        type=np.float64,
        description="Scalar mean summary for imported ceramic table column 'density_g_cm3'.",
    )
    density_g_cm3_min = Quantity(
        type=np.float64,
        description="Scalar min summary for imported ceramic table column 'density_g_cm3'.",
    )
    density_g_cm3_max = Quantity(
        type=np.float64,
        description="Scalar max summary for imported ceramic table column 'density_g_cm3'.",
    )

    relative_density_percent_mean = Quantity(
        type=np.float64,
        description="Scalar mean summary for imported ceramic table column 'relative_density_percent'.",
    )
    relative_density_percent_min = Quantity(
        type=np.float64,
        description="Scalar min summary for imported ceramic table column 'relative_density_percent'.",
    )
    relative_density_percent_max = Quantity(
        type=np.float64,
        description="Scalar max summary for imported ceramic table column 'relative_density_percent'.",
    )

    open_porosity_percent_mean = Quantity(
        type=np.float64,
        description="Scalar mean summary for imported ceramic table column 'open_porosity_percent'.",
    )
    open_porosity_percent_min = Quantity(
        type=np.float64,
        description="Scalar min summary for imported ceramic table column 'open_porosity_percent'.",
    )
    open_porosity_percent_max = Quantity(
        type=np.float64,
        description="Scalar max summary for imported ceramic table column 'open_porosity_percent'.",
    )

    hardness_gpa_mean = Quantity(
        type=np.float64,
        description="Scalar mean summary for imported ceramic table column 'hardness_gpa'.",
    )
    hardness_gpa_min = Quantity(
        type=np.float64,
        description="Scalar min summary for imported ceramic table column 'hardness_gpa'.",
    )
    hardness_gpa_max = Quantity(
        type=np.float64,
        description="Scalar max summary for imported ceramic table column 'hardness_gpa'.",
    )

    youngs_modulus_gpa_mean = Quantity(
        type=np.float64,
        description="Scalar mean summary for imported ceramic table column 'youngs_modulus_gpa'.",
    )
    youngs_modulus_gpa_min = Quantity(
        type=np.float64,
        description="Scalar min summary for imported ceramic table column 'youngs_modulus_gpa'.",
    )
    youngs_modulus_gpa_max = Quantity(
        type=np.float64,
        description="Scalar max summary for imported ceramic table column 'youngs_modulus_gpa'.",
    )

    flexural_strength_mpa_mean = Quantity(
        type=np.float64,
        description="Scalar mean summary for imported ceramic table column 'flexural_strength_mpa'.",
    )
    flexural_strength_mpa_min = Quantity(
        type=np.float64,
        description="Scalar min summary for imported ceramic table column 'flexural_strength_mpa'.",
    )
    flexural_strength_mpa_max = Quantity(
        type=np.float64,
        description="Scalar max summary for imported ceramic table column 'flexural_strength_mpa'.",
    )

    fracture_toughness_mpa_m05_mean = Quantity(
        type=np.float64,
        description="Scalar mean summary for imported ceramic table column 'fracture_toughness_mpa_m05'.",
    )
    fracture_toughness_mpa_m05_min = Quantity(
        type=np.float64,
        description="Scalar min summary for imported ceramic table column 'fracture_toughness_mpa_m05'.",
    )
    fracture_toughness_mpa_m05_max = Quantity(
        type=np.float64,
        description="Scalar max summary for imported ceramic table column 'fracture_toughness_mpa_m05'.",
    )

    wear_rate_mm3_nm_mean = Quantity(
        type=np.float64,
        description="Scalar mean summary for imported ceramic table column 'wear_rate_mm3_nm'.",
    )
    wear_rate_mm3_nm_min = Quantity(
        type=np.float64,
        description="Scalar min summary for imported ceramic table column 'wear_rate_mm3_nm'.",
    )
    wear_rate_mm3_nm_max = Quantity(
        type=np.float64,
        description="Scalar max summary for imported ceramic table column 'wear_rate_mm3_nm'.",
    )

    grain_size_um_mean = Quantity(
        type=np.float64,
        description="Scalar mean summary for imported ceramic table column 'grain_size_um'.",
    )
    grain_size_um_min = Quantity(
        type=np.float64,
        description="Scalar min summary for imported ceramic table column 'grain_size_um'.",
    )
    grain_size_um_max = Quantity(
        type=np.float64,
        description="Scalar max summary for imported ceramic table column 'grain_size_um'.",
    )


m_package.__init_metainfo__()
