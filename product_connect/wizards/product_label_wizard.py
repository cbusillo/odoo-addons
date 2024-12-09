from odoo import models, fields, api


class ProductLabelWizard(models.TransientModel):
    _name = "product.label.wizard"
    _description = "Product Label Wizard"

    product = fields.Many2one("product.template", store=True)
    default_code = fields.Char(string="SKU", help="Scan or type the SKU here.")
    name = fields.Char(related="product.name", readonly=True)
    quantity_available = fields.Float(related="product.qty_available", readonly=True)
    new_quantity = fields.Integer()
    use_available_qty = fields.Boolean(default=True)
    quantity_to_print = fields.Integer(default=1)

    @api.onchange("default_code")
    def _onchange_default_code(self) -> None:
        if self.default_code:
            self.product = self.env["product.template"].search([("default_code", "=", self.default_code)], limit=1)
            self.new_quantity = self.product.qty_available

    def action_print_labels(self) -> "odoo.values.ir_actions_client":
        self.ensure_one()
        self.product = self.env["product.template"].search([("default_code", "=", self.default_code)], limit=1)
        if not self.product:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Product not found",
                    "message": f"No product found with SKU {self.default_code}.",
                    "type": "danger",
                },
            }

        quantity_to_print = int(self.product.qty_available) if self.use_available_qty else self.quantity_to_print
        if self.new_quantity != self.product.qty_available:
            self.product.product_variant_id.update_quantity(self.new_quantity)
        if quantity_to_print > 0:
            self.product.print_product_labels(
                use_available_qty=self.use_available_qty, quantity_to_print=quantity_to_print
            )
        return {
            "type": "ir.actions.client",
            "res_model": "product.label.wizard",
            "target": "new",
        }
