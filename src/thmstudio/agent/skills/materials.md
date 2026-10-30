# Step: materials
Every region needs a material. Use a library entry (granite, sandstone, limestone, opalinus_clay, clay_soft, sand,
gravel, bentonite_saturated, concrete, cast_iron, copper) and change only what the user knows. Needed properties:
H: hydraulic_conductivity or permeability (+ specific_storage if transient). T: thermal_conductivity, density,
specific_heat. TH: + porosity, solid_density, solid_specific_heat. HC: permeability, porosity, dispersivities.
HM/TM/THM: + youngs_modulus, poissons_ratio, thermal_expansion (linear, solid), biot_coefficient.
Porosity is a fraction (0.2, not 20).
