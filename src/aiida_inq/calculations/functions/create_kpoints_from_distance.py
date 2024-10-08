"""
Calculation function to compute a k-point mesh from a kspacing value.
"""
from aiida.engine import calcfunction
from aiida import orm

@calcfunction
def create_kpoints_from_distance(structure, kspacing):
    """
    Generate a kpoint mesh for a given structure.

    :param structure: StructureData to which the mesh will be applied.
    :param kspacing: Spacing between kpoints in reciprocal space.

    :returns: KpointsData object with mesh.
    """

    kpoints = orm.KpointsData()
    kpoints.set_cell_from_structure(structure)
    kpoints.set_kpoints_mesh_from_density(kspacing.value, force_parity=False)

    return kpoints