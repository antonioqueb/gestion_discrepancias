# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class DiscrepancyLog(models.Model):
    _name = "discrepancy.log"
    _description = "Gestión de Discrepancias de Recepción"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"
    _mail_post_on_create = True

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
        string="Ubicación destino",
        compute="_compute_location_id",
        store=True,
        readonly=True,
        tracking=True,
    )
    description = fields.Text(
        string="Descripción / Motivo",
        tracking=True,
    )
    evidence_ids = fields.One2many(
        "discrepancy.image",
        "log_id",
        string="Evidencia fotográfica",
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("to_approve", "Por autorizar"),
            ("approved", "Autorizado"),
            ("corrected", "Corregido"),
            ("cancelled", "Cancelado"),
        ],
        string="Estado",
        default="draft",
        tracking=True,
    )
    line_ids = fields.One2many(
        "discrepancy.log.line",
        "log_id",
        string="Detalle de discrepancias",
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
                raise UserError(_("Debe agregar por lo menos una línea de discrepancia."))
            rec.state = "to_approve"

    def action_approve(self):
        for rec in self:
            rec.state = "approved"

    def action_apply_correction(self):
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("La discrepancia debe estar autorizada antes de corregir."))

            if not rec.location_id:
                raise UserError(_("No se encontró la ubicación destino del embarque."))

            for line in rec.line_ids:
                diff = line.difference_qty
                if diff:
                    rec.env["stock.quant"]._update_available_quantity(
                        line.product_id,
                        rec.location_id,
                        diff,
                        lot_id=False,
                    )
            rec.state = "corrected"

    def action_cancel(self):
        self.write({"state": "cancelled"})


class DiscrepancyLogLine(models.Model):
    _name = "discrepancy.log.line"
    _description = "Detalle de Discrepancias"
    _inherit = ["mail.thread"]
    _tracking_parent_field = "log_id"

    log_id = fields.Many2one(
        "discrepancy.log",
        string="Discrepancia",
        ondelete="cascade",
        required=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        tracking=True,
    )
    expected_qty = fields.Float(
        string="Cantidad esperada",
        required=True,
        digits="Product Unit of Measure",
        tracking=True,
    )
    received_qty = fields.Float(
        string="Cantidad recepcionada",
        required=True,
        digits="Product Unit of Measure",
        tracking=True,
    )
    product_uom_category_id = fields.Many2one(
        "uom.category",
        string="Categoría UoM",
        related="product_id.uom_id.category_id",
        readonly=True,
    )
    product_uom = fields.Many2one(
        "uom.uom",
        string="UdM",
        required=True,
        domain="[('category_id', '=', product_uom_category_id)]",
        tracking=True,
    )
    difference_qty = fields.Float(
        string="Diferencia",
        compute="_compute_difference_qty",
        store=True,
        digits="Product Unit of Measure",
        tracking=True,
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