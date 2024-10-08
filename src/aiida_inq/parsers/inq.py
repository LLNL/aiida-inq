# -*- coding: utf-8 -*-
from __future__ import absolute_import

from ase import units, Atoms, Atom
import numpy as np

from aiida.parsers import Parser
from aiida.engine import ExitCode
from aiida import orm
from aiida.plugins import DataFactory

from aiida.plugins import CalculationFactory

InqCalculation = CalculationFactory('inq.inq')


class InqParser(Parser):
    """
    Base parser for INQ calculations.
    """
    def __init__(self, node):
        """
        Initialize parser instance and check that node passed is
        from an INQ calculation.
        """
        from aiida.common import exceptions
        super(InqParser, self).__init__(node)
        if not issubclass(node.process_class, InqCalculation):
            raise exceptions.ParsingError("Can only parse INQ calculations")
        
        self.result_dict = {}
        self.state = None
        self.atoms = None

    def parse(self, **kwargs):
        """
        Parse retrieved file
        """

        temp_folder = kwargs['retrieved_temporary_folder']

        output_filename = self.node.get_option('output_filename')

        # Check that folder content is as expected
        files_retrieved = self.node.get_retrieve_temporary_list()
        files_expected = [output_filename]

        results_filename = ''
        if 'results' in self.node.inputs.parameters.get_dict():
            results_filename = self.node.get_option('results_filename')
            files_expected.append(results_filename)

        # Note: set(A) <= set(B) checks whether A is a subset of B
        if not set(files_expected) <= set(files_retrieved):
            self.logger.error("Found files '{}', expected to find '{}'".format(
                files_retrieved, files_expected))
            return self.exit_codes.ERROR_MISSING_OUTPUT_FILES

        # Read output file
        if results_filename:
            self.logger.info(f"Parsing '{results_filename}")
            with open(f'{temp_folder}/{results_filename}', 'r') as fhandle:
                results_lines = [line.strip('\n') for line in fhandle.readlines()]       

        self.logger.info("Parsing '{}'".format(output_filename))
        with open(f'{temp_folder}/{output_filename}', 'r') as fhandle:
            output_lines = [line.strip('\n') for line in fhandle.readlines()]

        # Check if INQ finished:
        inq_done = False
        if 'AiiDA DONE' in output_lines[-1]:
            inq_done = True
        if not inq_done:
            return self.exit_codes.ERROR_OUTPUT_STDOUT_INCOMPLETE

        if results_filename:
            lines = results_lines
        else:
            lines = output_lines

        for e, line in enumerate(lines):
            if 'Cell:' in line:
                self.state = 'cell'
                self.atoms = Atoms()
                continue
            elif 'Ions' in line:
                self.state = 'ions'
                continue
            elif 'Energy:' in line:
                self.state = 'energy'
                self.result_dict[self.state] = {'unit': 'eV'}
                continue
            elif 'Forces:' in line:
                self.state = 'forces'
                self.result_dict[self.state] = {'values': []}
                continue
            elif 'Total-steps:' in line:
                self.state = 'total-steps'
                continue
            elif 'Total-time:' in line:
                self.state = 'total-time'
                continue
            elif 'Time:' in line:
                self.state = 'time'
                self.result_dict[self.state] = {'values': []}
                continue
            elif 'Total-energy' in line:
                self.state = 'total-energy'
                self.result_dict[self.state] = {'values': []}
                self.result_dict['time'] = {'values': []}
                continue
            elif 'Dipole:' in line:
                self.state = 'dipole'
                self.result_dict[self.state] = {'values': []}
                self.result_dict['time'] = {'values': []}
                continue
            elif 'Current:' in line:
                self.state = 'current'
                self.result_dict[self.state] = {'values': []}
                self.result_dict['time'] = {'values': []}
                continue
            elif line == '':
                self.state = None


            match self.state:

                case 'cell':
                    cell_lines = lines[e:e+3]
                    cell = []
                    for cl in cell_lines:
                        cell.append(np.array(cl.split()[-3:]).astype('float'))
                    self.atoms.set_cell(cell)
                    self.state = None

                case 'ions':
                    temp = line.split()
                    self.atoms.append(Atom(temp[2], [temp[3], temp[4], temp[5]]))

                case 'energy':
                    values = line.split()
                    unit = getattr(units, values[-1])
                    self.result_dict[self.state][values[0]] = float(values[-2]) * unit

                case 'forces':
                    values = line.split()
                    self.result_dict[self.state]['values'].append(np.array(values).astype('float'))

                case 'total-steps':
                    self.result_dict[self.state] = int(line)

                case 'total-time':
                    self.result_dict[self.state] = float(line)

                case 'time':
                    self.result_dict[self.state]['values'].append(float(line))

                case 'total-energy':
                    values = line.split()
                    if len(values) > 2:
                        self.result_dict[self.state]['unit'] = values[-1].strip('[]')
                        self.result_dict['time']['unit'] = values[1].strip('[]')
                    else:
                        self.result_dict[self.state]['values'].append(float(values[1]))
                        self.result_dict['time']['values'].append(float(values[0]))

                case 'dipole':
                    self.parse_dipole_current(line)

                case 'current':
                    self.parse_dipole_current(line)      
            
        self.out('output_parameters', orm.Dict(dict=self.result_dict))

        if self.atoms:
            StructureData = DataFactory('core.structure')
            structure = StructureData(ase=self.atoms)
            self.out('output_structure', structure)

        return ExitCode(0)

    def parse_dipole_current(self, line):
        values = line.split()
        if len(values) > 4:
            self.result_dict[self.state]['unit'] = values[-1].strip('[]')
            self.result_dict['time']['unit'] = values[1].strip('[]')
        else:
            self.result_dict[self.state]['values'].append(np.array(values[1:]).astype('float').tolist())
            self.result_dict['time']['values'].append(float(values[0])) 