# Step: mesh
Set a general size and refine where things change fast: near heated or loaded boundaries, interfaces, wells and
sources (refinement target with size and growth 1.1 to 1.3). Build the mesh and look at the picture; fix quality
warnings. Element order is chosen automatically (quadratic displacement for mechanics). To check that the mesh is fine
enough, run, then compare with half_element_size.
