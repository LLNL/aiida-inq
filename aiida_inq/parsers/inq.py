# -*- coding: utf-8 -*-
from __future__ import absolute_import

from ase import units

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
            raise exceptions.ParsingError("Can only parse NWChem calculations")

    def parse(self, **kwargs):
        """
        Parse retrieved file
        """

        output_filename = self.node.get_option('output_filename')

        # Check that folder content is as expected
        files_retrieved = self.retrieved.list_object_names()
        files_expected = [output_filename]
        # Note: set(A) <= set(B) checks whether A is a subset of B
        if not set(files_expected) <= set(files_retrieved):
            self.logger.error("Found files '{}', expected to find '{}'".format(
                files_retrieved, files_expected))
            return self.exit_codes.ERROR_MISSING_OUTPUT_FILES

        # Read output file
        self.logger.info("Parsing '{}'".format(output_filename))
        with self.retrieved.open(output_filename, 'r') as fhandle:
            all_lines = [line.strip('\n') for line in fhandle.readlines()]

        # Check if INQ finished:
        #TODO: Handle the case of the 'ignore' keyword
        inq_done = False
        if 'AiiDA DONE' in all_lines[-1]:
            inq_done = True
        if not inq_done:
            return self.exit_codes.ERROR_OUTPUT_STDOUT_INCOMPLETE
        
        result_dict = {}

        state = None
        for line in all_lines:
            if 'Energy:' in line:
                state = 'energy'
                result_dict[state] = {'unit': 'eV'}
            if line == '':
                state = None
            if state == 'energy':
                values = line.split()
                unit = getattr(units, values[-1])
                result_dict[state][values[0]] = float(values[-2]) * unit
            
        self.out('output_parameters',orm.Dict(dict=result_dict))

        return ExitCode(0)