from aiida import load_profile
from aiida.orm import load_code, Dict, List
from aiida.plugins import DataFactory, WorkflowFactory
from aiida.engine import submit
from ase.build import bulk
import numpy as np


# Initiate the default profile.
load_profile()

# Get the workflow from AiiDA.
InqConvergenceWorkChain = WorkflowFactory('inq.convergence')

# Find the code you will use for the calculation.
code = load_code('inq@localhost')

# Create a structure
StructureData = DataFactory('core.structure')
atoms = bulk('Si', crystalstructure='diamond', a=5.43)
structure = StructureData(ase=atoms)

# General structure to provide override values to the protocol selected.
overrides = {
    'clean_workdir': True,
    'inq': {
        'parameters': {
            'results': {
                'ground-state': {
                    'energy': '',
                    'forces': ''
                }
            }
        },
        'metadata': {
            'options': {
                'resources': {
                    'tot_num_mpiprocs': 4,
                    'num_mpiprocs_per_machine': 4
                }
            }
        }
    }
}

energy = [f'{x} Ha' for x in range(8, 22, 2)]
kspacing = np.around(np.arange(0.10, 0.55, 0.05), 2).tolist()

builder = InqConvergenceWorkChain.get_builder_from_protocol(
    code,
    structure,
    energy_list = List(energy),
    kspacing_list = List(kspacing),
    protocol = 'fast', # Will reduce the kpoint grid.
    overrides = overrides
)

calc = submit(builder)

print(f'Created calculation with PK={calc.pk}')
