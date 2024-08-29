# -*- coding: utf-8 -*-
from collections import defaultdict
import numpy as np
from aiida import orm # type: ignore
from aiida.engine import CalcJob # type: ignore
from aiida.common.datastructures import CalcInfo, CodeInfo # type: ignore


class InqCalculation(CalcJob):
    """
    Base calculation class for the INQ code.
    """

    # Default input and output files
    _DEFAULT_INPUT_FILE  = 'aiida.in'
    _DEFAULT_OUTPUT_FILE = 'aiida.out'
    _DEFAULT_ERROR_FILE  = 'aiida.err'
 
    @classmethod
    def define(cls, spec):
        """Define the process specification."""
        # yapf: disable
        super().define(spec)
        spec.input(
            'parameters', 
            valid_type=orm.Dict, 
            required=True,
            help='Input parameters for the input file.'
        )
        spec.input(
            'structure', 
            valid_type=orm.StructureData, 
            required=True,
            help='The input structure.'
        )
        spec.input(
            'settings', 
            valid_type=orm.Dict, 
            required=False,
            help=(
                'Optional parameters to affect the way the calculation job '
                'is performed.'
            )
        )
        spec.input(
            'parent_folder',
            valid_type=orm.RemoteData,
            required=False,
            help=(
                'Optional working directory of a previous calculation to '
                'restart from.'
            )
        )
        spec.input(
            'metadata.options.input_filename', 
            valid_type=str, 
            default=cls._DEFAULT_INPUT_FILE
        )
        spec.input(
            'metadata.options.output_filename', 
            valid_type=str, 
            default=cls._DEFAULT_OUTPUT_FILE
        )
        spec.input(
            'metadata.options.scheduler_stdout',
            valid_type=str,
            default=cls._DEFAULT_OUTPUT_FILE
        )
        spec.input(
            'metadata.options.scheduler_stderr',
            valid_type=str,
            default=cls._DEFAULT_ERROR_FILE
        )
        spec.input(
            'metadata.options.parser_name', 
            valid_type=str, 
            default='inq.inq'
        )

        spec.output(
            'output_parameters', 
            valid_type=orm.Dict
        )
        spec.output(
            'output_structure', 
            valid_type=orm.StructureData, 
            required=False,
            help='The relaxed output structure.'
        )

        spec.default_output_node = 'output_parameters'

        spec.exit_code(201, 'INCORRECT_INPUT_PARAMETER',
            message='One of the point charges is not formatted correctly.')
        spec.exit_code(202, 'NO_RUN_TYPE_SPECIFIED',
            message='No run type was specified in the input parameters.')

        # yapf: enable

    def prepare_for_submission(self, folder):
        """
        Prepare the calculation job for submission by transforming input nodes
        into input files. In addition to the input files being written to the
        sandbox folder, a `CalcInfo` instance will be returned that contains 
        lists of files that need to be copied to the remote machine before 
        job submission, as well as file lists that are to be retrieved after 
        job completion. 
        
        :param folder: a sandbox folder to temporarily write files on disk. 
        
        :return: `aiida.common.datastructures.CalcInfo` instance.
        """

        # Verify inputs
        #self.verify_inputs()

        # Initialize settings if set
        if 'settings' in self.inputs:
            settings = self.inputs.settings.get_dict() # Might to make a check for this
        else:
            settings = {}

        # Initiate variables
        parameters = self.inputs.parameters.get_dict()
        structure = self.inputs.structure
        atoms = structure.get_ase()

        input_filename = folder.get_abs_path(self._DEFAULT_INPUT_FILE)
        f = open(input_filename, 'w')
        # Initiate the initial settings
        f.write("""#!/bin/bash

set -e
set -x

inq clear
""")
        # Initiate the cell
        cell = atoms.cell
        scale = np.max(cell)
        sc = cell/scale
        f.write(f"inq cell {' '.join(sc[0].astype('str'))} {' '.join(sc[1].astype('str'))} {' '.join(sc[2].astype('str'))} scale {scale} angstrom\n")

        # Add the atoms
        for atom in atoms:
            f.write(f"inq ions insert fractional {atom.symbol} {' '.join(atom.scaled_position.astype('str'))}\n")

        # Iterate through the parameters
        run_type = parameters.pop('run', None)
        run_type = list(run_type.keys())[0]
        if run_type is None:
            self.report(f'There was no run type specified.')
            self.exit_codes.NO_RUN_TYPE_SPECIFIED
        for key, val in parameters.items():
            for k, v in val.items():
                f.write(f"inq {key} {k} {v}\n")

        f.write(f'inq run {run_type}\n')

        # Echo that AiiDA finished.
        # Will be used to determine if a job finished.
        f.write(f'\necho "AiiDA DONE"')

        f.flush()

        local_copy_list = []
        remote_copy_list = []
        remote_symlink_list = []

        _default_commandline_params = [self._DEFAULT_INPUT_FILE]
        codeinfo =  CodeInfo()
        codeinfo.cmdline_params = _default_commandline_params
        codeinfo.stdout_name = self._DEFAULT_OUTPUT_FILE
        codeinfo.stderr_name = self._DEFAULT_ERROR_FILE
        codeinfo.code_uuid = self.inputs.code.uuid

        calcinfo = CalcInfo()
        calcinfo.codes_info = [codeinfo]
        calcinfo.stdin_name = self._DEFAULT_INPUT_FILE
        calcinfo.stdout_name = self._DEFAULT_OUTPUT_FILE
        calcinfo.local_copy_list = local_copy_list
        calcinfo.remote_copy_list = remote_copy_list
        calcinfo.remote_symlink_list = remote_symlink_list
        calcinfo.retrieve_list = []
        calcinfo.retrieve_temporary_list = [self._DEFAULT_OUTPUT_FILE,
                                            self._DEFAULT_ERROR_FILE]

        calcinfo.retrieve_singlefile_list = []

        return calcinfo