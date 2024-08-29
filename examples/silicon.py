from aiida import load_profile
from aiida.orm import load_code, Dict
from aiida.plugins import CalculationFactory, DataFactory
from aiida.engine import run,submit
from ase.build import bulk
import numpy as np


# Initiate the default profile
load_profile()

# Get the calculator from AiiDA
InqCalculation = CalculationFactory('inq.inq')

# Find the code you will use for the calculation
code = load_code('inq@localhost')

# Create a structure
StructureData = DataFactory('core.structure')
atoms = bulk('Si', crystalstructure='diamond', a=5.43)
atoms.positions
structure = StructureData(ase=atoms)

inputs = {
    'code': code,
    'structure': structure,
    'parameters' : Dict(dict={
        'electrons': {
            'cutoff': '35.0 Ha',
            'extra-states': 3
        },
        'kpoints': {
            'gamma': ''
            'insert': '-0.5 -0.5 -0.5 0.0'
        },
        'ground-state': {
            'tolerance': 1e-8
        },
        'run': {
            'ground-state': ''
        }
    }),
    'metadata': {
        #'dry_run': True,
        #'store_provenance': False,
        'options': {
            'resources': {
                'tot_num_mpiprocs': 4
            }
        }
    }
}

calc = run(InqCalculation, **inputs)
#print(f'Created calculation with PK={calc.pk}')
