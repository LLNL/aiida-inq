# -*- coding: utf-8 -*-
"""Workchain to run a convergence test using INQ."""

from aiida import orm
from aiida.common import AttributeDict
from aiida.engine import WorkChain, while_, ToContext
from aiida.plugins import CalculationFactory, WorkflowFactory

from aiida_inq.calculations.functions.create_kpoints_from_distance import create_kpoints_from_distance

from .protocols.utils import ProtocolMixin, suggested_energy_cutoff

import numpy as np

InqCalculation = CalculationFactory('inq.inq')
InqBaseWorkchain = WorkflowFactory('inq.base')


class InqConvergenceWorkChain(ProtocolMixin, WorkChain):
    """
    Workchain to run convergence tests using the Inq calculator.
    """

    @classmethod
    def define(cls, spec):

        super().define(spec)
        spec.expose_inputs(
            InqBaseWorkchain,
            namespace = 'conv',
            exclude = ('clean_workdir', 'inq.structure', 'max_iterations'),
            namespace_options = {
                'help': 'Inputs for the INQ Base Workchain.'
            }
        )
        spec.input(
            'structure',
            valid_type = orm.StructureData,
            help = 'The starting structure'
        )
        spec.input(
            'max_iter',
            valid_type = orm.Int,
            required = False,
            default = lambda: orm.Int(10),
            help = (
                'Maximum number of iterations to perform for both energy and '
                'kspacing calculations.'
            )
        )
        spec.input(
            'energy_delta',
            valid_type = orm.Float,
            required = False,
            default = lambda: orm.Float(1e-3),
            help = (
                'The value used to check if the total energy has converged. '
                'Since the parser returns values in eV, make sure to scale '
                'the value accordingly.'
            )
        )
        spec.input(
            'energy_start',
            valid_type = orm.Int,
            required = False,
            help = (
                'If provided, will use this energy cutoff as a starting point. '
                'Otherwise, the suggested energy cutoffs will be used from the '
                'pseudos.yaml protocol file. Units are considered to be Ha.'
            )
        )
        spec.input(
            'energy_step',
            valid_type = orm.Int,
            required = False,
            default = lambda: orm.Int(2),
            help = (
                'Default value for increasing the energy cutoff value. Units '
                'considered to be in Ha.'
            )
        )
        spec.input(
            'kspacing_start',
            valid_type = orm.Float,
            required = False,
            default = lambda: orm.Float(0.3),
            help = 'Starting kspacing value for convergence testing.'
        )
        spec.input(
            'kspacing_step',
            valid_type = orm.Float,
            required = False,
            default = lambda: orm.Float(0.05),
            help = 'Step value for reducing kspacing value.'
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

            while_(cls.should_run_energy)(
                cls.run_energy,
                cls.check_energy
            ),

            while_(cls.should_run_kspacing)(
                cls.run_kspacing,
                cls.check_kspacing
            ),

            cls.results,
        )

        spec.expose_outputs(InqCalculation)
        spec.output(
            'suggested',
            valid_type = orm.Dict,
            help = 'Suggested values for energy cutoff and kspacing.'
        )

        spec.exit_code(
            401,
            'INQ_CALCULATION_FAILED',
            message = 'An INQ calculation failed.'
        )
        spec.exit_code(
            402,
            'REACHED_MAXIMUM_ITERATIONS',
            message = 'Reached the maximum number of iterations for the workchain.'
        )

    @classmethod
    def get_protocol_filepath(cls):
        """Return ``pathlib.Path`` to the ``.yaml`` file that defines the protocols."""
        from importlib_resources import files

        from .protocols import inq as protocols # type: ignore
        return files(protocols) / 'convergence.yaml'

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

        # Pull the parameters and metadata information for the builder
        metadata = inputs['inq'].get('metadata', {})
        if options:
            metadata['options'] = options
        inputs['inq']['metadata'] = metadata

        inq = InqBaseWorkchain.get_builder_from_protocol(
            code,
            structure,
            protocol = protocol,
            overrides = inputs,
            options = options,
            **kwargs
        )

        # Put the needed inputs with the builder
        builder = cls.get_builder()

        builder.conv = inq
        builder.structure = structure
        builder.clean_workdir = inputs['clean_workdir']

        # See if any of the other values are passed in with kwargs.
        for kwarg in kwargs.keys():
            if kwarg in list(cls.spec().inputs.keys()):
                setattr(builder, kwarg, kwargs[kwarg])

        return builder

    def setup(self):
        """
        Call the `setup` of the `BaseRestartWorkChain` and then create the 
        inputs dictionary in `self.ctx.inputs`.

        This `self.ctx.inputs` dictionary will be used by the 
        `BaseRestartWorkChain` to submit the calculations in the internal loop.
        """

        self.ctx.inputs = AttributeDict()
        self.ctx.results = AttributeDict({'energy': {}, 'kspacing': {}})

        self.ctx.run_energy = True
        self.ctx.energy_iteration = 0
        self.ctx.prev_energy = 0
        energy_start = self.inputs.get('energy_start', None)
        if energy_start:
            self.ctx.energy = energy_start
        else:
            self.ctx.energy = suggested_energy_cutoff(self.inputs.structure)


        self.ctx.run_kspacing = True
        self.ctx.kspacing_iteration = 0
        self.ctx.kpoint_mesh = '1 1 1'
        self.ctx.kspacing_step = self.inputs.kspacing_step.value
        self.ctx.prev_kspacing = 0
        self.ctx.kspacing = self.inputs.get('kspacing_start', None)
        self.ctx.kspacing = self.ctx.kspacing.value

    def should_run_energy(self):
        """
        Simple check to see if energy has converged.
        """

        return self.ctx.run_energy 
    
    def run_energy(self):
        """
        Run a `InqBaseWorkChain` for each of the energy values.
        """

        inputs = AttributeDict(
            self.exposed_inputs(
                InqBaseWorkchain, namespace='conv'
            )
        )
        
        parameters = AttributeDict(inputs.inq.pop('parameters').get_dict())

        self.ctx.energy_iteration += 1
        inputs.inq.structure = self.inputs.structure
        energy = self.ctx.energy
        parameters.electrons.cutoff = f'{energy} Ha'
        inputs.inq.parameters = parameters

        label = f'energy_{energy}'
        inputs.metadata.label = label
        inputs.metadata.call_link_label = label

        energy_calc = self.submit(InqBaseWorkchain, **inputs)
        self.report(f'launching InqBaseWorkchain<{energy_calc.pk}> with energy cutoff {energy} Ha')

        return ToContext(energy_calc=energy_calc)
    
    def check_energy(self):
        """
        Inspect previous energy calculation.
        """

        calc = self.ctx.energy_calc

        if not calc.is_finished_ok:
            self.report(f'InqBaseWorkChain<{calc.pk}> failed.')
            return self.exit_codes.INQ_CALCULATION_FAILED
        
        results = calc.outputs.output_parameters.get_dict()
        total_energy = results['energy']['total']

        energy_diff = abs(self.ctx.prev_energy - total_energy)

        if energy_diff > self.inputs.energy_delta:
            self.ctx.prev_energy = total_energy
            self.ctx.energy += self.inputs.energy_step.value
            label = calc.label
            self.ctx.results.energy[label] = total_energy
        # If the energy difference is less than the delta than the previous step
        # can be considered the converged result.
        else:
            self.ctx.energy -= self.inputs.energy_step.value
            self.report(f'Converged with {self.ctx.energy} Ha and {self.ctx.energy_iteration} iterations.')
            self.ctx.run_energy = False

        if self.ctx.energy_iteration >= self.inputs.max_iter:
            self.report(f'Reached the maximum number of iterations ({self.inputs.max_iter}).')
            self.ctx.run_energy = False
            return self.exit_codes.REACHED_MAXIMUM_ITERATIONS

        return
    
    def should_run_kspacing(self):
        """
        Check to see if should run another kspacing simulation.
        """

        return self.ctx.run_kspacing 
    
    def run_kspacing(self):
        """
        Run a `InqBaseWorkChain` for each of the kspacing values.
        """

        inputs = AttributeDict(
            self.exposed_inputs(
                InqBaseWorkchain, namespace='conv'
            )
        )
        
        parameters = AttributeDict(inputs.inq.pop('parameters').get_dict())

        parameters.electrons.cutoff = f'{self.ctx.energy} Ha'
        parameters.kpoints.grid = ''

        self.ctx.kspacing_iteration += 1
        inputs.inq.structure = self.inputs.structure

        # Convert kspacing to kpoint mesh
        calc_inputs = {
            'structure': inputs.inq.structure,
            'kspacing': self.ctx.kspacing
        }
        kpoints = create_kpoints_from_distance(**calc_inputs)    
        kpoints = kpoints.get_kpoints_mesh()[0]
        kpoints = ' '.join([str(k) for k in kpoints])

        while kpoints == self.ctx.kpoint_mesh:
            self.ctx.kspacing = np.around(self.ctx.kspacing - self.ctx.kspacing_step, 2)
            calc_inputs['kspacing'] = self.ctx.kspacing
            kpoints = create_kpoints_from_distance(**calc_inputs)
            kpoints = kpoints.get_kpoints_mesh()[0]
            kpoints = ' '.join([str(k) for k in kpoints])

        self.ctx.kpoint_mesh = kpoints
       
        label = f'kspacing_{"_".join(str(self.ctx.kspacing).split("."))}'
        parameters.kpoints.grid = self.ctx.kpoint_mesh
        inputs.inq.parameters = parameters

        inputs.metadata.label = label
        inputs.metadata.call_link_label = label

        kspacing_calc = self.submit(InqBaseWorkchain, **inputs)
        self.report(f'launching InqBaseWorkchain<{kspacing_calc.pk}> with kspacing {self.ctx.kspacing}')

        return ToContext(kspacing_calc=kspacing_calc)
    
    def check_kspacing(self):
        """
        Inspect previous kspacing calculation.
        """

        calc = self.ctx.kspacing_calc

        if not calc.is_finished_ok:
            self.report(f'InqBaseWorkChain<{calc.pk}> failed.')
            return self.exit_codes.INQ_CALCULATION_FAILED
        
        results = calc.outputs.output_parameters.get_dict()
        total_energy = results['energy']['total']

        energy_diff = abs(self.ctx.prev_kspacing - total_energy)

        if energy_diff > self.inputs.energy_delta:
            self.ctx.prev_kspacing = total_energy
            self.ctx.kspacing = np.around(self.ctx.kspacing - self.ctx.kspacing_step, 2)
            label = calc.label
            self.ctx.results.kspacing[label] = total_energy
        # Previous step will be the converged kspacing value
        else:
            self.ctx.kspacing = np.around(self.ctx.kspacing + self.ctx.kspacing_step, 2)
            self.report(f'Converged with {self.ctx.kspacing} kspacing and {self.ctx.kspacing_iteration} iterations.')
            self.ctx.run_kspacing = False

        if self.ctx.kspacing_iteration >= self.inputs.max_iter:
            self.report(f'Reached the maximum number of iterations ({self.inputs.max_iter}).')
            self.ctx.run_kspacing = False
            return self.exit_codes.REACHED_MAXIMUM_ITERATIONS

        return
    
    def results(self):
        """
        Gather the final results and set it as output.
        """

        suggested = orm.Dict(dict = {
            'energy': self.ctx.energy,
            'kspacing': self.ctx.kspacing
        })
        suggested.store()

        results = orm.Dict(dict = self.ctx.results)
        results.store()

        self.out('suggested', suggested)
        self.out('output_parameters', results)
        
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