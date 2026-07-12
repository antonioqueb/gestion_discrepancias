# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPicking(models.Model):
    """Transferencia interna generada por `discrepancy.log._create_correction_picking`:
    corrección de inventario real y trazable en vez de un ajuste directo de quant."""
    _inherit = "stock.picking"

    discrepancy_log_id = fields.Many2one(
        "discrepancy.log", string="Discrepancia de Origen", readonly=True, copy=False,
    )
