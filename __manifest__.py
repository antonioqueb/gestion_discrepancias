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
