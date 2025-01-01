from odoo import models, fields, api


class ProductInventoryWizardLine(models.TransientModel):
    _name = "product.inventory.wizard.line"
    _description = "Product Inventory Wizard Line"

    wizard = fields.Many2one("product.inventory.wizard", ondelete="cascade")
    product = fields.Many2one("product.template")
    name = fields.Char(related="product.name", readonly=True)
    bin = fields.Char(related="product.bin", readonly=True)
    qty_available = fields.Float(related="product.qty_available", readonly=True)
    quantity_scanned = fields.Integer()

    selected = fields.Boolean()


class ProductInventoryWizard(models.TransientModel):
    _name = "product.inventory.wizard"
    _description = "Product Inventory Wizard"

    scan_box = fields.Char(string="Scan", help="Scan or type the SKU/Bin here.")
    products = fields.One2many("product.inventory.wizard.line", "wizard")
    bin = fields.Char()

    use_available_qty = fields.Boolean(default=True)
    quantity_to_print = fields.Integer(default=1)

    @api.onchange("scan_box")
    def _onchange_default_code(self) -> None:
        if not self.scan_box:
            return

        if self.scan_box[0].isdigit():
            product_searched = self.env["product.template"].search([("default_code", "=", self.scan_box)], limit=1)
            if product_searched in self.products.mapped("product"):
                self.products.filtered(lambda p: p.product == product_searched).quantity_scanned += 1
            else:
                self.products += self.env["product.inventory.wizard.line"].create(
                    {
                        "wizard": self.id,
                        "product": product_searched.id,
                        "quantity_scanned": 1,
                        "selected": True,
                    }
                )
        else:
            self.bin = self.scan_box.strip().upper()
            self.products.unlink()
            products_with_bin = self.env["product.template"].search([("bin", "=", self.bin)])
            self.products = self.env["product.inventory.wizard.line"].create(
                [
                    {
                        "wizard": self.id,
                        "product": product.id,
                        "quantity_scanned": 0,
                        "selected": True,
                    }
                    for product in products_with_bin
                ]
            )

        self.scan_box = ""

    def action_print_labels(self) -> "odoo.values.ir_actions_client":
        self.ensure_one()
        self.product = self.env["product.template"].search([("default_code", "=", self.scan_box)], limit=1)
        if not self.products:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Product not found",
                    "message": f"No product found with SKU {self.scan_box}.",
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
            "res_model": "product.inventory.wizard",
            "target": "new",
        }
