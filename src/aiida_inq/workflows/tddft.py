# -*- coding: utf-8 -*-
"""Workchain to run a convergence test using INQ."""

from aiida import orm
from aiida.common import AttributeDict
from aiida.engine import WorkChain, ToContext
from aiida.plugins import CalculationFactory, WorkflowFactory

from .protocols.utils import ProtocolMixin, suggested_energy_cutoff

import numpy as np

InqCalculation = CalculationFactory('inq.inq')
InqBaseWorkchain = WorkflowFactory('inq.base')


class InqTDDFTWorkChain(ProtocolMixin, WorkChain):
    """
    Workchain to run convergence tests using the Inq calculator.
    """

    @classmethod
    def define(cls, spec):

        super().define(spec)
        spec.expose_inputs(
            InqBaseWorkchain,
            namespace = 'gs',
            exclude = ('clean_workdir', 'structure', 'inq.structure'),
            namespace_options = {
                'help': 'Inputs for the Ground State calculation.'
            }
        )
        spec.expose_inputs(
            InqBaseWorkchain,
            namespace = 'tddft',
            exclude = ('clean_workdir', 'structure', 'inq.structure'),
            namespace_options = {
                'help': 'Inputs for the TDDFT calculation.'
            }
        )
        spec.input(
            'structure',
            valid_type = orm.StructureData,
            help = 'The starting structure.'
        )
        spec.input(
            'clean_workdir',
            valid_type = orm.Bool,
            help = (
                'If `True`, work directories of all called calculations will '
                'be cleaned at the end of the workflow.'
            )
        )

        spec.outline(
            cls.setup,

            cls.run_ground_state,
            cls.check_ground_state,

            cls.run_tddft,
            cls.check_tddft,

            cls.results,
        )

        spec.expose_outputs(InqCalculation)

        spec.exit_code(
            401,
            'INQ_CALCULATION_FAILED',
            message = 'An INQ calculation failed.'
        )

    @classmethod
    def get_protocol_filepath(cls):
        """Return ``pathlib.Path`` to the ``.yaml`` file that defines the protocols."""
        from importlib_resources import files

        from .protocols import inq as protocols # type: ignore
        return files(protocols) / 'tddft.yaml'

    @classmethod
    def get_builder_from_protocol(
        cls,
        code: orm.Code,
        structure: orm.StructureData,
        protocol: str = None,
        overrides: dict = None,
        options: dict = None,
        **kwargs
    ):
        """
        Return a builder prepopulated with inputs based on a provided 
        protocol. If no protocol is given, the default protocol is set 
        as moderate.

        :param code: 
            The ``Code`` instance configured for the ``inq.inq`` plugin.
        :param structure:
            The ``StructureData`` instance to use.
        :param protocol:
            Protocol to use. Options are moderate, precise, or fast.
        :param overrides:
            Optional dictionary of inputs that will override the values 
            provided from the protocol file.
        :param options:
            A dictionary of options that will be recursively set for the 
            ``metadata.options`` input of all the ``CalcJobs`` that are 
            nested in this work chain.

        :return:
            A builder instance with all the inputs defined and ready to 
            launch.
        """

        # Get input values
        inputs = cls.get_protocol_inputs(protocol, overrides)

        gs = InqBaseWorkchain.get_builder_from_protocol(
            code,
            structure,
            protocol = protocol,
            overrides = inputs.get('gs', None),
            options = options,
            **kwargs
        )

        tddft = InqBaseWorkchain.get_builder_from_protocol(
            code,
            structure,
            protocol = protocol,
            overrides = inputs.get('tddft', None),
            options = options,
            **kwargs
        )

        # Put the needed inputs with the builder
        builder = cls.get_builder()

        builder.gs = gs
        builder.tddft = tddft
        builder.structure = structure
        builder.clean_workdir = inputs['clean_workdir']

        return builder

    def setup(self):
        """
        Call the `setup` of the `BaseRestartWorkChain` and then create the 
        inputs dictionary in `self.ctx.inputs`.

        This `self.ctx.inputs` dictionary will be used by the 
        `BaseRestartWorkChain` to submit the calculations in the internal loop.
        """

        self.ctx.results = {}

        return
    
    def run_ground_state(self):
        """
        
        """
        inputs = AttributeDict(
            self.exposed_inputs(
                InqBaseWorkchain, namespace='gs'
            )
        )

        inputs.structure = self.inputs.structure

        label = f'Ground_State'
        inputs.metadata.label = label
        inputs.metadata.call_link_label = label

        ground_state = self.submit(InqBaseWorkchain, **inputs)
        self.report(f'launching InqBaseWorkchain<{ground_state.pk}> for ground state calculation.')

        return ToContext(ground_state=ground_state)
    
    def check_ground_state(self):
        """
        Inspect previous ground state calculation.
        """

        calc = self.ctx.ground_state

        if not calc.is_finished_ok:
            self.report(f'InqBaseWorkChain<{calc.pk}> failed.')
            return self.exit_codes.INQ_CALCULATION_FAILED
        
        self.ctx.calc_parent_folder = calc.outputs.remote_folder
        self.ctx.current_structure = calc.outputs.output_structure
        self.ctx.results['ground_state'] = calc.outputs.output_parameters.get_dict()

        return
    
    def run_tddft(self):
        """
        
        """
        inputs = AttributeDict(
            self.exposed_inputs(
                InqBaseWorkchain, namespace='tddft'
            )
        )

        inputs.structure = self.inputs.structure
        inputs.inq.parent_folder = self.ctx.calc_parent_folder

        label = f'TDDFT'
        inputs.metadata.label = label
        inputs.metadata.call_link_label = label

        tddft = self.submit(InqBaseWorkchain, **inputs)
        self.report(f'launching InqBaseWorkchain<{tddft.pk}> for tddft calculation.')

        return ToContext(tddft=tddft)
    
    def check_tddft(self):
        """
        Inspect previous tddft calculation.
        """

        calc = self.ctx.tddft

        if not calc.is_finished_ok:
            self.report(f'InqBaseWorkChain<{calc.pk}> failed.')
            return self.exit_codes.INQ_CALCULATION_FAILED
        
        self.ctx.calc_parent_folder = calc.outputs.remote_folder
        self.ctx.current_structure = calc.outputs.output_structure
        self.ctx.results['tddft'] = calc.outputs.output_parameters.get_dict()

        return    
    
    def results(self):
        """
        Gather the final results and set it as output.
        """

        results = orm.Dict(dict = self.ctx.results)
        results.store()

        self.out('output_parameters', results)
        self.out('output_structure', self.ctx.current_structure)
        
        return
    
    def on_terminated(self):
        """
        Clean working directories from workflow if `clean_workdir=True`.
        """
        super().on_terminated()

        if self.inputs.clean_workdir.value is False:
            self.report('remote folders will not be cleaned')
            return

        cleaned_calcs = []

        for called_descendant in self.node.called_descendants:
            if isinstance(called_descendant, orm.CalcJobNode):
                try:
                    called_descendant.outputs.remote_folder._clean()  # pylint: disable=protected-access
                    cleaned_calcs.append(called_descendant.pk)
                except (IOError, OSError, KeyError):
                    pass

        if cleaned_calcs:
            self.report(f"cleaned remote folders of calculations: {' '.join(map(str, cleaned_calcs))}")