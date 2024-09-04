# -*- coding: utf-8 -*-
"""Workchain to run a convergence test using INQ."""

from aiida import orm
from aiida.common import AttributeDict
from aiida.engine import WorkChain, while_
from aiida.plugins import CalculationFactory, WorkflowFactory

InqCalculation = CalculationFactory('inq.inq')
InqBaseWorkchain = WorkflowFactory('inq.base')


class InqConvergenceWorkChain(WorkChain):
    """
    Workchain to run convergence tests using the Inq calculator.
    """

    _process_class = InqCalculation

    @classmethod
    def define(cls, spec):

        super().define(spec)
        spec.expose_inputs(
            InqBaseWorkchain, 
            namespace='inq',
            exclude = (),
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
            'clean_workdir',
            valid_type = orm.Bool,
            help = (
                'If `True`, work directories of all called calculations will '
                'be cleaned at the end of the workflow.'
            )
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

    def setup(self):
        """
        Call the `setup` of the `BaseRestartWorkChain` and then create the 
        inputs dictionary in `self.ctx.inputs`.

        This `self.ctx.inputs` dictionary will be used by the 
        `BaseRestartWorkChain` to submit the calculations in the internal loop.
        """

        super(InqBaseWorkchain, self).setup()
        self.ctx.inputs = AttributeDict(
            self.exposed_inputs(InqCalculation, 'inq'))