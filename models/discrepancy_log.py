# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class DiscrepancyLog(models.Model):
    _name = "discrepancy.log"
    _description = "Gestión de Discrepancias de Recepción"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="Folio",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("Nuevo"),
        tracking=True,
    )

    picking_id = fields.Many2one(
        "stock.picking",
        string="Embarque relacionado",
        required=True,
        tracking=True,
    )

    location_id = fields.Many2one(
        "stock.location",
        compute="_compute_location_id",
        store=True,
        readonly=True,
    )

    description = fields.Text(string="Descripción")

    evidence_ids = fields.One2many(
        "discrepancy.image",
        "log_id",
        string="Evidencia",
    )

    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("to_approve", "Por autorizar"),
            ("approved", "Autorizado"),
            ("corrected", "Corregido"),
            ("cancelled", "Cancelado"),
        ],
        default="draft",
    )

    line_ids = fields.One2many(
        "discrepancy.log.line",
        "log_id",
        string="Líneas",
    )

    @api.depends("picking_id.location_dest_id")
    def _compute_location_id(self):
        for rec in self:
            rec.location_id = rec.picking_id.location_dest_id or False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "discrepancy.log.sequence"
                ) or _("Nuevo")
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Debe agregar líneas."))
            rec.state = "to_approve"

    def action_approve(self):
        self.state = "approved"

    def action_apply_correction(self):
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Debe estar autorizado."))

            for line in rec.line_ids:
                if line.difference_qty:
                    self.env["stock.quant"]._update_available_quantity(
                        line.product_id,
                        rec.location_id,
                        line.difference_qty,
                    )

            rec.state = "corrected"

    def action_cancel(self):
        self.state = "cancelled"


class DiscrepancyLogLine(models.Model):
    _name = "discrepancy.log.line"
    _description = "Detalle de Discrepancias"

    log_id = fields.Many2one(
        "discrepancy.log",
        required=True,
        ondelete="cascade",
    )

    product_id = fields.Many2one(
        "product.product",
        required=True,
    )

    expected_qty = fields.Float(required=True)
    received_qty = fields.Float(required=True)

    product_uom = fields.Many2one(
        "uom.uom",
        string="Unidad",
        required=True,
    )

    difference_qty = fields.Float(
        compute="_compute_difference_qty",
        store=True,
    )

    @api.depends("expected_qty", "received_qty")
    def _compute_difference_qty(self):
        for line in self:
            line.difference_qty = line.received_qty - line.expected_qty

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom = self.product_id.uom_id
        else:
            self.product_uom = False

    @api.constrains("product_id", "product_uom")
    def _check_uom(self):
        for rec in self:
            if rec.product_id and rec.product_uom:
                if rec.product_uom != rec.product_id.uom_id:
                    raise UserError(
                        _("En Odoo 19 la unidad debe coincidir con la del producto.")
                    )