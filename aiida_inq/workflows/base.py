# -*- coding: utf-8 -*-
"""Base workchain to run an INQ calculation."""

from aiida.common import AttributeDict
from aiida.engine import BaseRestartWorkChain, while_
from aiida.plugins import CalculationFactory

InqCalculation = CalculationFactory('inq.inq')


class InqBaseWorkChain(BaseRestartWorkChain):
    """
    Workchain to run an Inq calculation with automated error handling 
    and restarts.
    """

    _process_class = InqCalculation

    @classmethod
    def define(cls, spec):

        super(InqBaseWorkChain, cls).define(spec)
        spec.expose_inputs(InqCalculation, namespace='inq')

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

        super(InqBaseWorkChain, self).setup()
        self.ctx.inputs = AttributeDict(
            self.exposed_inputs(InqCalculation, 'inq'))