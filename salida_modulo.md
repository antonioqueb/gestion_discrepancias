-e ### models/discrepancy_image.py
```
# models/discrepancy_image.py
from odoo import fields, models

class DiscrepancyImage(models.Model):
    _name = 'discrepancy.image'
    _description = 'Imagen de Evidencia'

    name = fields.Char("Descripción")
    image_1920 = fields.Image("Imagen", required=True)
```

-e ### models/__init__.py
```
from . import discrepancy_log
from . import discrepancy_image
```

-e ### models/discrepancy_log.py
```
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class DiscrepancyLog(models.Model):
    _name = "discrepancy.log"
    _description = "Gestión de Discrepancias de Recepción"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"
    _mail_post_on_create = True

    # ─── Cabecera ────────────────────────────────────────────────────────────
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
        related="picking_id.location_dest_id",
        store=True,
        readonly=True,
    )

    description = fields.Text(string="Descripción / Motivo", tracking=True)

    evidence_ids = fields.Many2many(
        "discrepancy.image",
        string="Evidencia fotográfica",
        tracking=True,
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

    # ─── Secuencia ──────────────────────────────────────────────────────────
    @api.model
    def create(self, vals):
        if vals.get("name", _("Nuevo")) == _("Nuevo"):
            vals["name"] = self.env["ir.sequence"].next_by_code(
                "discrepancy.log.sequence"
            ) or _("Nuevo")
        return super().create(vals)

    # ─── Acciones de flujo ──────────────────────────────────────────────────
    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Debe agregar por lo menos una línea de discrepancia."))
            rec.state = "to_approve"

    def action_approve(self):
        for rec in self:
            rec.state = "approved"

    def action_apply_correction(self):
        """Ajusta inventario según las diferencias y pasa a CORREGIDO."""
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("La discrepancia debe estar autorizada antes de corregir."))
            for line in rec.line_ids:
                diff = line.difference_qty
                if diff:
                    # Ajuste inmediato de inventario sin detener la operación
                    self.env["stock.quant"]._update_available_quantity(
                        line.product_id,
                        rec.location_id,
                        diff,
                        lot_id=False
                    )
            rec.state = "corrected"

    def action_cancel(self):
        self.state = "cancelled"


class DiscrepancyLogLine(models.Model):
    _name = "discrepancy.log.line"
    _description = "Detalle de Discrepancias"
    _inherit = ["mail.thread"]
    _tracking_parent_field = "log_id"

    log_id = fields.Many2one(
        "discrepancy.log",
        string="Discrepancia",
        ondelete="cascade",
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
    product_uom = fields.Many2one(
        "uom.uom",
        string="UdM",
        required=True,
        domain="[('category_id', '=', product_id.uom_id.category_id)]",
        tracking=True,
    )
    difference_qty = fields.Float(
        string="Diferencia",
        compute="_compute_difference_qty",
        store=True,
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
```

-e ### views/discrepancy_log_views.xml
```
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <!-- Menú raíz -->
    <menuitem id="menu_discrepancy_root"
              name="Discrepancias"
              sequence="15"/>

    <!-- Acción principal -->
    <record id="action_discrepancy_log" model="ir.actions.act_window">
        <field name="name">Gestión de Discrepancias</field>
        <field name="res_model">discrepancy.log</field>
        <field name="view_mode">list,form</field>
        <field name="help" type="html">
            <p>Registra discrepancias con evidencia, autorízalas y corrige inventario sin detener la operación.</p>
        </field>
    </record>

    <!-- Menú secundario -->
    <menuitem id="menu_discrepancy_log"
              name="Bitácora"
              parent="menu_discrepancy_root"
              action="action_discrepancy_log"
              sequence="25"/>

    <!-- Vista lista -->
    <record id="view_discrepancy_log_list" model="ir.ui.view">
        <field name="name">discrepancy.log.list</field>
        <field name="model">discrepancy.log</field>
        <field name="arch" type="xml">
            <list>
                <field name="name"/>
                <field name="picking_id"/>
                <field name="state"/>
                <field name="create_date"/>
            </list>
        </field>
    </record>

    <!-- Vista formulario -->
    <record id="view_discrepancy_log_form" model="ir.ui.view">
        <field name="name">discrepancy.log.form</field>
        <field name="model">discrepancy.log</field>
        <field name="arch" type="xml">
            <form string="Discrepancia de Recepción">
                <header>
                    <button name="action_submit" type="object" string="Enviar"
                            modifiers="{'invisible': [['state','!=','draft']]}"/>
                    <button name="action_approve" type="object" string="Autorizar"
                            modifiers="{'invisible': [['state','!=','to_approve']]}"/>
                    <button name="action_apply_correction" type="object" string="Aplicar corrección"
                            modifiers="{'invisible': [['state','!=','approved']]}"/>
                    <button name="action_cancel" type="object" string="Cancelar"
                            modifiers="{'invisible': [['state','in',['corrected','cancelled']]]}"/>
                    <field name="state" widget="statusbar"
                           statusbar_visible="draft,to_approve,approved,corrected,cancelled"/>
                </header>

                <sheet>
                    <group>
                        <field name="name" readonly="1"/>
                        <field name="picking_id" domain="[('state','not in',('cancel','done'))]"/>
                        <field name="description" placeholder="Motivo de la discrepancia…"/>
                    </group>

                    <notebook>
                        <page string="Detalle">
                            <field name="line_ids" mode="list,form">
                                <list>
                                    <field name="product_id"/>
                                    <field name="expected_qty"/>
                                    <field name="received_qty"/>
                                    <field name="difference_qty"/>
                                    <field name="product_uom"/>
                                </list>
                                <form>
                                    <group>
                                        <field name="product_id"/>
                                        <field name="expected_qty"/>
                                        <field name="received_qty"/>
                                        <field name="product_uom"/>
                                    </group>
                                </form>
                            </field>
                        </page>
                        <page string="Evidencia">
                            <field name="evidence_ids" widget="many2many_image"/>

                        </page>
                    </notebook>
                </sheet>

                <!-- Chatter nativo -->
                <chatter/>
            </form>
        </field>
    </record>
</odoo>
```

### __init__.py
```
# -*- coding: utf-8 -*-
from . import models
```
### __manifest__.py
```
# -*- coding: utf-8 -*-
{
    "name": "Gestión de Discrepancias",
    "version": "1.0",
    "summary": "Flujo de discrepancias con evidencia fotográfica, autorización y re-manifiesto",
    "author": "Alphaqueb Consulting",
    "license": "LGPL-3",
    "category": "Operations",
    "depends": ["mail", "stock", "product", "uom"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/discrepancy_log_views.xml",
    ],
    "installable": True,
    "application": False,
}
```
