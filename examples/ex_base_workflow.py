from aiida import load_profile
from aiida.orm import load_code, Dict
from aiida.plugins import DataFactory, WorkflowFactory
from aiida.engine import submit
from ase.build import bulk

# Initiate the default profile.
load_profile()

# Get the calculator from AiiDA.
InqBaseWorkChain = WorkflowFactory('inq.base')

# Find the code you will use for the calculation.
code = load_code('inq@localhost')

# Create a structure
StructureData = DataFactory('core.structure')
atoms = bulk('Si', crystalstructure='diamond', a=5.43)
structure = StructureData(ase=atoms)

# General structure to provide override values to the protocol selected.
overrides = {
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
                    'tot_num_mpiprocs': 4
                }
            }
        }
    }
}

builder = InqBaseWorkChain.get_builder_from_protocol(
    code,
    structure,
    protocol = 'fast', # Will reduce the kpoint grid.
    overrides = overrides
)

calc = submit(builder)

print(f'Created calculation with PK={calc.pk}')
