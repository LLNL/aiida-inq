# -*- coding: utf-8 -*-
"""Workchain to run a convergence test using INQ."""

from aiida import orm
from aiida.common import AttributeDict
from aiida.engine import WorkChain, while_
from aiida.plugins import CalculationFactory, WorkflowFactory

from .protocols.utils import ProtocolMixin

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
            exclude = ('clean_workdir', 'inq.structure'),
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
            'energy_list',
            valid_type = orm.List,
            required = True,
            help = (
                'List of values to do convergence tests on. Must define the '
                'units in the list. For example, ["30 Ry",...,"80 Ry"].'
            )
        )
        spec.input(
            'kspacing_list',
            valid_type = orm.List,
            required = True,
            help = 'List of kspacing values for convergence testing.'
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

            cls.run_energy,
            cls.check_energy,

            cls.run_kspacing,
            cls.check_kspacing,

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
        energy_list: orm.List,
        kspacing_list: orm.List,
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
        inputs = cls.get_protocol_inputs(structure, protocol, overrides)

        # Pull the parameters and metadata information for the builder
        metadata = inputs['inq'].get('metadata', {})
        if options:
            metadata['options'] = options
        inputs['inq']['metadata'] = metadata

        inq = InqBaseWorkchain.get_builder_from_protocol(
            code,
            structure,
            protocol = protocol,
            overrides = inputs.get('inq', None),
            options = options,
            **kwargs
        )

        # Put the needed inputs with the builder
        builder = cls.get_builder()

        builder.inq = inq.inq
        builder.structure = structure
        builder.energy_list = energy_list
        builder.kspacing_list = kspacing_list
        builder.clean_workdir = inputs['clean_workdir']

        return builder

    def setup(self):
        """
        Call the `setup` of the `BaseRestartWorkChain` and then create the 
        inputs dictionary in `self.ctx.inputs`.

        This `self.ctx.inputs` dictionary will be used by the 
        `BaseRestartWorkChain` to submit the calculations in the internal loop.
        """

        self.ctx.inputs = AttributeDict(
            self.exposed_inputs(
                InqBaseWorkchain
            )
        )
        
        self.ctx.parameters = self.ctx.inputs.inq.parameters.get_dict()
        
        self.ctx.inputs.settings = self.ctx.inputs.settings.get_dict() if 'settings' in self.ctx.inputs else {}

        self.ctx.results = AttributeDict({'energy': {}, 'kspacing': {}})

    def run_energy(self):
        """
        Run a `InqBaseWorkChain` for each of the energy values.
        """

        inputs = self.ctx.inputs
        inputs.pop('settings')
        inputs.inq.structure = self.inputs.structure
        inputs.inq.parameters.electrons = AttributeDict({'cutoff': 0})

        for energy in self.inputs.energy_list:
            label = f'energy_{"_".join(energy.split())}'
            inputs.inq.parameters.electrons.cutoff = energy

            inputs.metadata.label = label
            inputs.metadata.call_link_label = label

            future = self.submit(InqBaseWorkchain, **inputs)
            self.report(f'launching InqBaseWorkchain<{future.pk}> with energy cutoff {energy}')
            self.to_context(**{f'energy.{"_".join(energy.split())}': future})

        return
    
    def check_energy(self):
        """
        Inspect all previous energy calculations.
        """

        min_energy, energy_cutoff = 0, 0

        for label, workchain in self.ctx.energy.items():
                if not workchain.is_finished_ok:
                    self.report(f'InqBaseWorkChain` failed for energy calculation {label}.')
                    return self.exit_codes.INQ_CALCULATION_FAILED
                else:
                    results = workchain.outputs.output_parameters.get_dict()
                    inputs = workchain.inputs.inq.parameters.get_dict()
                    energy = results['energy']['total']
                    cutoff = inputs['electrons']['cutoff']
                    if energy < min_energy:
                        energy_cutoff = cutoff
                    self.ctx.results.energy[label] = energy

        self.ctx.energy_cutoff = energy_cutoff

        return
    
    def run_kspacing(self):
        """
        Run a `InqBaseWorkChain` for each of the kspacing values.
        """

        inputs = self.ctx.inputs
        inputs.inq.structure = self.inputs.structure
        inputs.inq.parameters.electrons = AttributeDict({'cutoff': self.ctx.energy_cutoff})
        inputs.inq.parameters.kpoints = AttributeDict({'grid': ''})

        # Convert kspacing to kpoint mesh
        kpoint_mesh = ['','']
        for kspacing in self.inputs.kspacing_list:
            kpoints = orm.KpointsData()
            kpoints.set_cell_from_structure(inputs.inq.structure)
            kpoints.set_kpoints_mesh_from_density(kspacing, force_parity=False)
            kpoints = kpoints.get_kpoints_mesh()[0]
            kpoints = ' '.join([str(k) for k in kpoints])

            if kpoints not in kpoint_mesh[:][1]:
                kpoint_mesh.append((kspacing, kpoints))

                label = f'kspacing_{"_".join(str(kspacing).split("."))}'
                inputs.inq.parameters.kpoints.grid = kpoints

                inputs.metadata.label = label
                inputs.metadata.call_link_label = label

                future = self.submit(InqBaseWorkchain, **inputs)
                self.report(f'launching InqBaseWorkchain<{future.pk}> with kspacing {kspacing}')
                self.to_context(**{f"kspacing.{'_'.join(str(kspacing).split('.'))}": future})

        return
    
    def check_kspacing(self):
        """
        Inspect all previous kspacing calculations.
        """
        min_energy, kspacing = 0, 0
        for label, workchain in self.ctx.kspacing.items():
                label = float('.'.join(label.split('_')))
                if not workchain.is_finished_ok:
                    self.report(f'InqBaseWorkChain` failed for kspacing {label}.')
                    return self.exit_codes.INQ_CALCULATION_FAILED
                else:
                    results = workchain.outputs.output_parameters.get_dict()
                    energy = results['energy']['total']

                    if energy < min_energy:
                        kspacing = label

                    self.ctx.results.kspacing[label] = energy

        self.ctx.kspacing = kspacing

        return
    
    def results(self):
        """
        Gather the final results and set it as output.
        """

        suggested = orm.Dict(dict = {
            'energy': self.ctx.energy_cutoff,
            'kspacing': self.ctx.kspacing
        })

        results = orm.Dict(dict = self.ctx.results)

        self.out('suggested', suggested)
        self.out('output_parameters', self.ctx.results)
        
        return