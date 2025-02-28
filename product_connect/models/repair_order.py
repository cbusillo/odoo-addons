from odoo import fields, models


class RepairOrder(models.Model):
    _inherit = "repair.order"

    motor = fields.Many2one(
        "motor", related="product_id.motor", store=True, index=True, readonly=True, ondelete="restrict"
    )

    def action_repair_done(self):
        res = super().action_repair_done()
        for order in self:
            for move in order.move_ids:
                pass
                # decrement quantity from shopify
            cost = sum([m.product_tmpl_id.standard_price * m.quantity for m in order.move_ids])
            cost_per_unit = (
                cost / order.product_id.product_tmpl_id.qty_available
                if order.product_id.product_tmpl_id.is_ready_for_sale
                else order.product_id.product_tmpl_id.initial_quantity
            )
            order.product_id.standard_price += cost_per_unit
        return res
