from aiida import load_profile
from aiida.orm import load_code
from aiida.plugins import DataFactory, WorkflowFactory
from aiida.engine import submit, run
from ase.build import bulk


# Initiate the default profile.
load_profile()

# Get the workflow from AiiDA.
InqTDDFTWorkChain = WorkflowFactory('inq.tddft')

# Find the code you will use for the calculation.
code = load_code('inq@localhost')

# Create a structure
StructureData = DataFactory('core.structure')
atoms = bulk('Si', crystalstructure='diamond', a=5.43)
structure = StructureData(ase=atoms)

# General structure to provide override values to the protocol selected.
overrides = {
    'clean_workdir': False,
    'gs': {
        'inq': {
            'parameters': {
                'results': {
                    'ground-state': {
                        'energy': '',
                        'forces': ''
                    }
                },
                'run': {
                    'ground-state': ''
                }
            },
            'metadata': {
                'options': {
                    'resources': {
                        'tot_num_mpiprocs': 14
                    }
                }
            }
        }
    },
    'tddft': {
        'inq': {
            'parameters': {
                'real-time': {
                    'time-step': '0.025 atu',
                    'num-steps': 10,
                    'ions': 'ehrenfest',
                    'observables': ['dipole', 'current']
                },
                'results': {
                    'real-time': {
                        'total-energy': '',
                        'dipole': '',
                        'current': ''
                    }
                },
                'run': {
                    'real-time': ''
                }
            },
            'metadata': {
                'options': {
                    'resources': {
                        'tot_num_mpiprocs': 14
                    }
                }
            }
        }
    }
}

builder = InqTDDFTWorkChain.get_builder_from_protocol(
    code,
    structure,
    protocol = 'fast', # Will reduce the kpoint grid.
    overrides = overrides
)

# If you want to follow the output leave the run command.
run(builder)
# Otherwise, comment run and uncomment the following commands.
#calc = submit(builder)
#print(f'Created calculation with PK={calc.pk}')
