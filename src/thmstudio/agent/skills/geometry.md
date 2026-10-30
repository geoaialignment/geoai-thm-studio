# Step: geometry
Shapes: rect (2D section or plan view with horizontal layers, bottom to top), rect_inclusion (rectangle with one
circular body), axisym_well (radial section around a well, r from the well wall), axisym_source (radial section around
a heat source on the axis: point, or canister with optional buffer; symmetric = upper half only), box (3D, flow and heat
only). Names you give to layers become region names. Boundaries are named left/right/bottom/top (rect), well/outer
(axisym_well), axis/outer/bottom/top (axisym_source), left/right/front/back/bottom/top (box).
Make the model large enough: heat spreads about sqrt(kappa t) (granite: 7 m per year).
A rect can have named segments of its top or bottom side (for a source on part of the top), and its corners are named points (corner_top_left, ...) where a pressure or head can be fixed.
