# -*- coding: utf-8 -*-
from __future__ import absolute_import

from ase import units
import numpy as np

from aiida.parsers import Parser
from aiida.engine import ExitCode
from aiida import orm

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
        
        result_dict = {}

        if results_filename:
            lines = results_lines
        else:
            lines = output_lines

        state = None
        for line in lines:
            if 'Energy:' in line:
                state = 'energy'
                result_dict[state] = {'unit': 'eV'}
                continue
            if 'Forces:' in line:
                state = 'forces'
                result_dict[state] = {'values': []}
                continue
            if line == '':
                state = None
            if state == 'energy':
                values = line.split()
                unit = getattr(units, values[-1])
                result_dict[state][values[0]] = float(values[-2]) * unit
            elif state == 'forces':
                values = line.split()
                result_dict[state]['values'].append(np.array(values).astype('float'))
            
        self.out('output_parameters',orm.Dict(dict=result_dict))

        return ExitCode(0)