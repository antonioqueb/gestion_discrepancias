# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

GROUP_MANAGER = 'gestion_discrepancias.group_discrepancia_manager'
GROUP_AUTORIZADOR = 'gestion_discrepancias.group_discrepancia_autorizador'


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

    # Modo de manifestación de la discrepancia
    measurement_mode = fields.Selection(
        [
            ("kg", "Kilogramos"),
            ("pcs", "Piezas"),
        ],
        string="Modo de Medición",
        default="kg",
        required=True,
        tracking=True,
        help="Define si las cantidades esperada/recibida se manejan en kilogramos "
             "o en piezas. Aplica a todas las líneas del documento.",
    )

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

    correction_picking_ids = fields.One2many(
        "stock.picking",
        "discrepancy_log_id",
        string="Transferencias de Corrección",
    )
    correction_picking_count = fields.Integer(compute="_compute_correction_picking_count")

    approved_by = fields.Many2one("res.users", string="Autorizado por", readonly=True, copy=False)
    approved_date = fields.Datetime(string="Fecha de Autorización", readonly=True, copy=False)

    @api.depends("picking_id.location_dest_id")
    def _compute_location_id(self):
        for rec in self:
            rec.location_id = rec.picking_id.location_dest_id or False

    @api.depends("correction_picking_ids")
    def _compute_correction_picking_count(self):
        for rec in self:
            rec.correction_picking_count = len(rec.correction_picking_ids)

    def _ensure_group(self, group_xmlid):
        user = self.env.user
        if user.has_group(GROUP_MANAGER) or user.has_group(group_xmlid):
            return
        raise AccessError(_("No tiene permisos para realizar esta acción sobre la discrepancia."))

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
            if not rec.evidence_ids:
                raise UserError(_(
                    "Debe adjuntar al menos una evidencia fotográfica antes de enviar la "
                    "discrepancia a autorización."
                ))
            rec.state = "to_approve"

    def action_approve(self):
        self._ensure_group(GROUP_AUTORIZADOR)
        for rec in self:
            if rec.state != "to_approve":
                raise UserError(_("Solo se puede autorizar una discrepancia que esté 'Por autorizar'."))
            if rec.create_uid.id == self.env.uid and not self.env.user.has_group(GROUP_MANAGER):
                raise UserError(_(
                    "Por segregación de funciones, quien reportó esta discrepancia no puede "
                    "autorizarla. Solicite la autorización a otro usuario."
                ))
            rec.write({
                "state": "approved",
                "approved_by": self.env.uid,
                "approved_date": fields.Datetime.now(),
            })

    def action_apply_correction(self):
        """Aplica la corrección de inventario mediante una transferencia interna
        real de `stock.picking`/`stock.move` (trazable, auditable y reversible
        desde Inventario > Transferencias), en vez de ajustar `stock.quant`
        directamente. La conversión de cantidades (kg/piezas) no cambia respecto
        a `difference_qty`, calculada en `discrepancy.log.line`.
        """
        self._ensure_group(GROUP_AUTORIZADOR)
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Debe estar autorizado."))
            rec._create_correction_picking()
            rec.state = "corrected"

    def _get_correction_picking_type(self, company):
        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "internal"),
            ("warehouse_id.company_id", "=", company.id),
        ], limit=1)
        if not picking_type:
            raise UserError(_(
                'No se encontró un tipo de operación de "Transferencias Internas" configurado '
                "para la compañía %s. Configure uno en Inventario > Configuración > Tipos de "
                "Operación antes de aplicar la corrección."
            ) % company.name)
        return picking_type

    def _get_adjustment_location(self, company):
        location = self.env["stock.location"].search([
            ("usage", "=", "inventory"),
            ("company_id", "in", [company.id, False]),
        ], limit=1)
        if not location:
            raise UserError(_(
                'No se encontró una ubicación de ajuste de inventario ("Inventory adjustment") '
                "para la compañía %s."
            ) % company.name)
        return location

    def _create_correction_picking(self):
        self.ensure_one()
        lines_with_diff = self.line_ids.filtered(lambda l: l.difference_qty)
        if not lines_with_diff:
            return
        company = self.picking_id.company_id or self.env.company
        picking_type = self._get_correction_picking_type(company)
        adjustment_location = self._get_adjustment_location(company)

        gains = lines_with_diff.filtered(lambda l: l.difference_qty > 0)
        losses = lines_with_diff.filtered(lambda l: l.difference_qty < 0)
        if gains:
            self._create_correction_picking_direction(
                gains, picking_type, adjustment_location, self.location_id, company,
            )
        if losses:
            self._create_correction_picking_direction(
                losses, picking_type, self.location_id, adjustment_location, company,
            )

    def _create_correction_picking_direction(self, lines, picking_type, src_location, dst_location, company):
        self.ensure_one()
        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": src_location.id,
            "location_dest_id": dst_location.id,
            "origin": _("Corrección de discrepancia %s") % self.name,
            "company_id": company.id,
            "discrepancy_log_id": self.id,
        })
        for line in lines:
            self.env["stock.move"].create({
                "name": line.product_id.display_name,
                "product_id": line.product_id.id,
                "product_uom_qty": abs(line.difference_qty),
                "product_uom": line.product_uom.id,
                "picking_id": picking.id,
                "location_id": src_location.id,
                "location_dest_id": dst_location.id,
                "company_id": company.id,
            })
        picking.action_confirm()
        picking.action_assign()
        if "picked" in picking.move_ids._fields:
            picking.move_ids.write({"picked": True})
        try:
            picking.with_context(skip_backorder=True).button_validate()
        except Exception as exc:
            raise UserError(_(
                'No se pudo validar la transferencia de corrección "%s": %s'
            ) % (picking.name, exc))
        return picking

    def action_view_correction_pickings(self):
        self.ensure_one()
        if len(self.correction_picking_ids) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": "stock.picking",
                "view_mode": "form",
                "res_id": self.correction_picking_ids.id,
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("Transferencias de Corrección"),
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": [("id", "in", self.correction_picking_ids.ids)],
        }

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

    # Modo heredado del documento padre (solo UI / reporte)
    measurement_mode = fields.Selection(
        related="log_id.measurement_mode",
        string="Modo",
        store=True,
        readonly=True,
    )

    product_id = fields.Many2one(
        "product.product",
        required=True,
    )

    expected_qty = fields.Float(
        string="Cantidad Esperada",
        required=True,
    )
    received_qty = fields.Float(
        string="Cantidad Recibida",
        required=True,
    )

    product_uom = fields.Many2one(
        "uom.uom",
        string="Unidad",
        required=True,
    )

    difference_qty = fields.Float(
        compute="_compute_difference_qty",
        store=True,
    )

    # Label dinámico para mostrar en el reporte/UI
    unit_label = fields.Char(
        string="Unidad Display",
        compute="_compute_unit_label",
    )

    @api.depends("expected_qty", "received_qty")
    def _compute_difference_qty(self):
        for line in self:
            line.difference_qty = line.received_qty - line.expected_qty

    @api.depends("measurement_mode", "product_uom")
    def _compute_unit_label(self):
        for line in self:
            if line.measurement_mode == "pcs":
                line.unit_label = "pz"
            else:
                line.unit_label = line.product_uom.name or "kg"

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