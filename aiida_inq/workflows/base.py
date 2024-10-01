# -*- coding: utf-8 -*-
"""Base workchain to run an INQ calculation."""

from aiida import orm
from aiida.common import AttributeDict
from aiida.engine import BaseRestartWorkChain, while_
from aiida.plugins import CalculationFactory
from .protocols.utils import suggested_energy_cutoff

from .protocols.utils import ProtocolMixin # type: ignore

InqCalculation = CalculationFactory('inq.inq')


class InqBaseWorkChain(ProtocolMixin, BaseRestartWorkChain):
    """
    Workchain to run an Inq calculation with automated error handling 
    and restarts.
    """

    _process_class = InqCalculation

    @classmethod
    def define(cls, spec):

        super().define(spec)
        spec.expose_inputs(
            InqCalculation, 
            namespace='inq',
        )
        spec.input(
            'structure',
            valid_type = orm.StructureData,
            required = True,
            help = 'The input structure.'
        )
        spec.input(
            'kpoints',
            valid_type = orm.KpointsData,
            required = False,
            help = 'Kpoint grid.'
        )
        spec.input(
            'kpoints_spacing',
            valid_type = orm.Float,
            required = False,
            help = 'The spacing between kpoints in reciprocal space.'
        )
        spec.input(
            'clean_workdir',
            valid_type = orm.Bool,
            default = lambda: orm.Bool(False),
            help = 'Whether to clean all related work folders.'
        )

        spec.outline(
            cls.setup,
            while_(cls.should_run_process)(
                cls.run_process,
                cls.inspect_process,
            ),
            cls.results,
        )

        spec.expose_outputs(InqCalculation)

    @classmethod
    def get_protocol_filepath(cls):
        from importlib_resources import files

        from .protocols import inq as protocols # type: ignore
        return files(protocols) / 'base.yaml'
        
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

        # Check to see if cutoff has been set in overrides.
        electrons = inputs['inq']['parameters'].get('electrons', None)
        if electrons:
            cutoff = inputs['inq']['parameters']['electrons'].get('cutoff', None)
        else:
            cutoff = None
        # Otherwise, put a suggested energy cutoff.
        if not cutoff:
            cutoff = suggested_energy_cutoff(structure, inputs, protocol)
            if not electrons:
                inputs['inq']['parameters']['electrons'] = {}
            inputs['inq']['parameters']['electrons']['cutoff'] = f'{cutoff} Ha'

        # Pull the parameters and metadata information for the builder
        parameters = inputs['inq'].get('parameters', {})
        metadata = inputs['inq'].get('metadata', {})
        if options:
            metadata['options'] = options

        # Setup the kpoints data
        kpoints = parameters.get('kpoints', None)
        if not kpoints:
            kspacing = inputs.get('kpoints_distance')
            kpoints = orm.KpointsData()
            kpoints.set_cell_from_structure(structure)
            kpoints.set_kpoints_mesh_from_density(kspacing, force_parity=False)
            kpoints = kpoints.get_kpoints_mesh()[0]
            parameters['kpoints'] = {}
            parameters['kpoints']['grid'] = ' '.join([str(k) for k in kpoints])

        # Put the needed inputs with the builder
        builder = cls.get_builder()

        builder.inq.code = code
        builder.inq.structure = structure
        builder.inq.parameters = parameters
        builder.inq.metadata = metadata
        builder.clean_workdir = inputs['clean_workdir']

        return builder
    
    def setup(self):
        """
        Call the `setup` of the `BaseRestartWorkChain` and then create the 
        inputs dictionary in `self.ctx.inputs`.

        This `self.ctx.inputs` dictionary will be used by the 
        `BaseRestartWorkChain` to submit the calculations in the internal loop.
        """

        super(InqBaseWorkChain, self).setup()
        self.ctx.inputs = AttributeDict(
            self.exposed_inputs(InqCalculation, 'inq'))
        
        self.ctx.inputs.parameters = self.inputs.inq.parameters