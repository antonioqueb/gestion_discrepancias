# models/discrepancy_image.py
from odoo import fields, models

class DiscrepancyImage(models.Model):
    _name = 'discrepancy.image'
    _description = 'Imagen de Evidencia'

    name = fields.Char("Descripción")
    image_1920 = fields.Image("Imagen", required=True)