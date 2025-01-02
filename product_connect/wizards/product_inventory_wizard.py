from odoo import models, fields, api


class ProductInventoryWizardLine(models.TransientModel):
    _name = "product.inventory.wizard.line"
    _description = "Product Inventory Wizard Line"

    wizard = fields.Many2one("product.inventory.wizard", ondelete="cascade")
    product = fields.Many2one("product.template")
    default_code = fields.Char(related="product.default_code", readonly=True)
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

    def _handle_product_scan(self) -> None:
        product_searched = self.env["product.template"].search([("default_code", "=", self.scan_box)], limit=1)
        scanned_product = self.products.filtered(lambda p: p.product == product_searched)
        if scanned_product:
            scanned_product.quantity_scanned += 1
            if scanned_product.quantity_scanned == scanned_product.product.qty_available:
                scanned_product.selected = True

        else:

            self.products += self.env["product.inventory.wizard.line"].create(
                {
                    "wizard": self.id,
                    "product": product_searched.id,
                    "quantity_scanned": 1,
                    "selected": False,
                }
            )

            self.products = self.products.sorted(key=lambda p: p.selected)

    def _handle_bin_scan(self) -> None:
        scanned_bin = self.scan_box.strip().upper()

        self.products = [(5, 0, 0)]
        self.bin = scanned_bin

        products_with_bin = self.env["product.template"].search([("bin", "=", self.bin)])
        self.products = self.env["product.inventory.wizard.line"].create(
            [
                {
                    "wizard": self.id,
                    "product": product.id,
                    "quantity_scanned": 0,
                    "selected": False,
                }
                for product in products_with_bin
            ]
        )

    @api.onchange("scan_box")
    def _onchange_scan_box(self) -> None:
        if not self.scan_box:
            return

        if self.scan_box[0].isdigit():
            self._handle_product_scan()
        else:
            self._handle_bin_scan()

        self.scan_box = ""

    def action_apply_bin(self) -> "odoo.values.ir_actions_client" or "odoo.values.ir_actions_act_window":
        if not self.bin:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "No bin to apply",
                    "message": "No bin selected to apply.",
                    "type": "warning",
                },
            }

        return {
            "type": "ir.actions.act_window",
            "name": "Confirm Bin Update",
            "res_model": "product.inventory.wizard",
            "view_mode": "form",
            "view_id": self.env.ref("product_connect.view_product_inventory_wizard_form_confirm").id,
            "target": "new",
            "res_id": self.id,
        }

    def action_confirm_bin_update(self) -> tuple["odoo.values.ir_actions_client", "odoo.values.ir_actions_act_window"]:
        products_to_update = self.products.filtered(lambda p: p.bin != self.bin)
        products_to_update.mapped("product").write({"bin": self.bin})

        if self.env.context.get("scan_next_bin"):
            self._handle_bin_scan()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Success",
                "message": f"Updated bin location for {len(products_to_update)} products",
                "type": "success",
            },
        }, {
            "type": "ir.actions.act_window_close",
        }

    def action_search(self) -> "odoo.values.ir_actions_act_window":
        self.action_apply_bin()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "target": "main",
            "context": self._context,
        }

    def action_print_product_labels(
        self,
    ) -> "odoo.values.ir_actions_client" or "odoo.values.ir_actions_act_window":
        product_ids_selected = self.products.filtered(lambda p: p.selected).mapped("product.id")
        products_to_print = self.env["product.template"].search([("id", "in", product_ids_selected)])
        if not products_to_print:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "No labels to print",
                    "message": f"No products selected to print labels.",
                    "type": "warning",
                },
            }
        for product in products_to_print:
            quantity_to_print = product.qty_available if self.use_available_qty else self.quantity_to_print
            if quantity_to_print:
                product.print_product_labels(quantity_to_print=quantity_to_print)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Success",
                "message": f"Printed labels for {len(products_to_print)} products",
                "type": "success",
            },
        }

    def action_print_bin_label(self) -> "odoo.values.ir_actions_client":
        if not self.bin:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "No bin to print",
                    "message": f"No bin selected to print labels.",
                    "type": "warning",
                },
            }
        label_data = ["", "Bin: ", self.bin]
        label = self.products.product.generate_label_base64(label_data, barcode=self.bin)
        self.products.product._print_labels([label], odoo_job_type="product_label", job_name="Bin Label")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Success",
                "message": f"Printed bin label for {self.bin}",
                "type": "success",
            },
        }
