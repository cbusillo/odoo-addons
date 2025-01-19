from odoo import fields, models


class RepairOrder(models.Model):
    _inherit = "repair.order"

    motor = fields.Many2one(
        "motor", related="product_id.motor", store=True, index=True, readonly=True, ondelete="restrict"
    )
