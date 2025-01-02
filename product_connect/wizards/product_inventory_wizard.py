from typing import Literal

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

    is_selected = fields.Boolean(string="X")


class ProductInventoryWizard(models.TransientModel):
    _name = "product.inventory.wizard"
    _description = "Product Inventory Wizard"

    scan_box = fields.Char(string="Scan", help="Scan or type the SKU/Bin here.")
    products = fields.One2many("product.inventory.wizard.line", "wizard")
    bin = fields.Char()
    use_available_quantity = fields.Boolean(default=True)

    product_labels_to_print = fields.Integer(default=1)
    bin_needs_update = fields.Boolean(compute="_compute_bin_needs_update")
    total_product_labels_to_print = fields.Integer(compute="_compute_total_product_labels_to_print")
    count_of_products_not_selected = fields.Integer(compute="_compute_products_not_selected")
    count_of_products_not_selected_with_quantity = fields.Integer(
        compute="_compute_products_not_selected_with_quantity"
    )

    @api.depends("products", "products.is_selected")
    def _compute_products_not_selected(self) -> None:
        for wizard in self:
            wizard.count_of_products_not_selected = len(wizard.products.filtered(lambda p: not p.is_selected))

    @api.depends("products", "products.is_selected", "products.qty_available")
    def _compute_products_not_selected_with_quantity(self) -> None:
        for wizard in self:
            wizard.count_of_products_not_selected_with_quantity = len(
                wizard.products.filtered(lambda p: not p.is_selected and p.qty_available)
            )

    def notify_user(
        self, message: "str", title: str or None, message_type: Literal["info", "success", "warning", "danger"] | None
    ):
        self.env["bus.bus"]._sendone(
            self.env.user.partner_id,
            "simple_notification",
            {"title": title or "Notification", "message": message, "sticky": False, "type": message_type or "info"},
        )

    @api.depends(
        "products",
        "products.qty_available",
        "use_available_quantity",
        "product_labels_to_print",
        "products.is_selected",
    )
    def _compute_total_product_labels_to_print(self) -> None:
        for wizard in self:
            wizard.total_product_labels_to_print = sum(
                p.qty_available if wizard.use_available_quantity else wizard.product_labels_to_print
                for p in wizard.products.filtered("is_selected")
            )

    @api.depends("products", "products.bin", "bin", "products.is_selected")
    def _compute_bin_needs_update(self) -> None:
        for wizard in self:
            wizard.bin_needs_update = any(p.bin != wizard.bin for p in wizard.products)

    def _handle_product_scan(self) -> bool:
        product_searched = self.env["product.template"].search([("default_code", "=", self.scan_box)], limit=1)
        if not product_searched:
            return False

        product_in_wizard = self.products.filtered(lambda p: p.product == product_searched)
        if product_in_wizard:
            product_in_wizard.quantity_scanned += 1
            if product_in_wizard.quantity_scanned == product_in_wizard.product.qty_available:
                product_in_wizard.is_selected = True
            else:
                product_in_wizard.is_selected = False

        else:
            self.products += self.env["product.inventory.wizard.line"].create(
                {
                    "wizard": self.id,
                    "product": product_searched.id,
                    "quantity_scanned": 1,
                    "is_selected": True,
                }
            )

        return True

    def _handle_bin_scan(self) -> None:
        if self.bin and self.products:
            self.action_apply_bin_changes()
        self.bin = self.scan_box.strip().upper()
        self._load_bin_products()

    def _load_bin_products(self) -> None:
        self.products = [(5, 0, 0)]
        products_with_bin_and_quantity = self.env["product.template"].search(
            [("bin", "=", self.bin), ("qty_available", ">", 0)]
        )
        self.products = self.env["product.inventory.wizard.line"].create(
            [
                {
                    "wizard": self.id,
                    "product": product.id,
                    "quantity_scanned": 0,
                    "is_selected": False,
                }
                for product in products_with_bin_and_quantity
            ]
        )

    @api.onchange("scan_box")
    def _onchange_scan_box(self) -> None or "odoo.values.ir_actions_act_window":
        if not self.scan_box:
            return

        if self.scan_box[0].isalpha():
            self._handle_bin_scan()
        else:
            if not self._handle_product_scan():
                return {
                    "warning": {
                        "title": "Item not found",
                        "message": f"SKU {self.scan_box} not found in Odoo.",
                    }
                }

        self.scan_box = ""

    def action_apply_bin_changes(self) -> None:
        if not self.bin:
            self.notify_user("No bin selected to apply.", "No bin to apply", "warning")
            return

        products_to_update = self.products.filtered(lambda p: p.bin != self.bin)
        if products_to_update:
            products_to_update.mapped("product").write({"bin": self.bin})
            self.notify_user(
                f"Updated bin location to {self.bin} for {len(products_to_update)} products", "Success", "success"
            )
            return
        self.notify_user("No products needed bin update.", "No changes", "info")

    def action_print_product_labels(
        self,
    ) -> "odoo.values.ir_actions_client" or "odoo.values.ir_actions_act_window":
        product_ids_selected = self.products.filtered(lambda p: p.is_selected).mapped("product.id")
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
            quantity_to_print = product.qty_available if self.use_available_quantity else self.product_labels_to_print
            if quantity_to_print:
                product.print_product_labels(quantity_to_print=quantity_to_print)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Success",
                "message": f"Sent label(s) for {len(products_to_print)} product(s) to printer.",
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
                "message": f"Sent bin label for {self.bin} to printer.",
                "type": "success",
            },
        }
