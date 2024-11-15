import logging
import re
from datetime import timedelta
from typing import Any

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class ProductType(models.Model):
    _name = "product.type"
    _description = "Part Type"
    _sql_constraints = [
        ("name_uniq", "unique (name)", "Part Type name already exists !"),
    ]

    name = fields.Char(required=True, index=True)
    ebay_category_id = fields.Integer(string="eBay Category ID", index=True)

    products = fields.One2many("product.template", "part_type")
    products_import = fields.One2many("product.import", "part_type")
    motor_products = fields.One2many("motor.product", "part_type")


class ProductCondition(models.Model):
    _name = "product.condition"
    _description = "Product Condition"
    _sql_constraints = [("name_uniq", "unique (name)", "Product Condition name already exists !")]

    name = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True, readonly=True)
    ebay_condition_id = fields.Integer(string="eBay Condition ID", index=True)

    products = fields.One2many("product.template", "condition")
    products_import = fields.One2many("product.import", "condition")
    motor_products = fields.One2many("motor.product", "condition")


class ProductBase(models.AbstractModel):
    _name = "product.base"
    _inherit = ["mail.thread", "label.mixin"]
    _description = "Product Base"
    _order = "create_date desc"
    _sql_constraints = [
        ("default_code_uniq", "unique(default_code)", "SKU must be unique."),
    ]

    name = fields.Char(index=True)
    motor = fields.Many2one("motor", ondelete="restrict", readonly=True)
    default_code = fields.Char("SKU", index=True, copy=False, readonly=True)
    create_date = fields.Datetime(index=True)

    images = fields.One2many("product.image", "product_tmpl_id")
    image_count = fields.Integer(compute="_compute_image_count", store=True)
    image_icon = fields.Binary(related="images.image_1920", string="Image Icon")

    mpn = fields.Char(string="MPN", index=True)
    first_mpn = fields.Char(compute="_compute_first_mpn", store=True)
    manufacturer = fields.Many2one("product.manufacturer", index=True)
    part_type = fields.Many2one("product.type", index=True)
    part_type_name = fields.Char(related="part_type.name", store=True, index=True, string="Part Type Name")
    condition = fields.Many2one("product.condition", index=True)

    length = fields.Integer()
    width = fields.Integer()
    height = fields.Integer()
    weight = fields.Float()

    bin = fields.Char(index=True)
    qty_available = fields.Float(string="Quantity")

    list_price = fields.Float(string="Price")
    standard_price = fields.Float(string="Cost")

    website_description = fields.Html()

    active = fields.Boolean(default=True)
    has_recent_messages = fields.Boolean(compute="_compute_has_recent_messages", store=True)
    is_listable = fields.Boolean(default=False)

    @api.model_create_multi
    def create(self, vals_list: list["odoo.values.product_base"]) -> "odoo.model.product_base":
        for vals in vals_list:
            if "default_code" not in vals:
                vals["default_code"] = self.get_next_sku()
        return super().create(vals_list)

    # noinspection PyShadowingNames
    @api.model
    def read_group(
        self,
        domain: list,
        fields: list,
        groupby: list,
        offset: int = 0,
        limit: int | None = None,
        orderby: str = "",
        lazy: bool = True,
    ) -> list[dict[str, Any]]:
        groups = super().read_group(domain, fields, groupby, offset=offset, limit=limit, orderby=orderby, lazy=lazy)
        fields_to_sum_with_qty = {"list_price", "standard_price"}
        if not fields_to_sum_with_qty.intersection(fields):
            return groups
        for group in groups:
            if "__domain" in group:
                group["list_price"] = sum(
                    product["list_price"] * product["qty_available"] for product in self.search(group["__domain"])
                )
                group["standard_price"] = sum(
                    product["standard_price"] * product["qty_available"] for product in self.search(group["__domain"])
                )

        return groups

    @api.constrains("default_code")
    def _check_sku(self) -> None:
        for product in self:
            if not product.default_code:
                continue
            if not re.match(r"^\d{4,8}$", str(product.default_code)):
                raise ValidationError(_("SKU must be 4-8 digits."))

    def get_next_sku(self) -> str:
        sequence = self.env.ref("product_connect.sequence_product_template_default_code")
        padding = sequence.padding
        max_sku = "9" * padding
        search_model_names = [
            "product.template",
            "product.import",
            "motor.product",
        ]
        search_models = [self.env[model_name].sudo() for model_name in search_model_names]
        while (new_sku := self.env["ir.sequence"].next_by_code("product.template.default_code")) <= max_sku:
            domain = [("default_code", "=", new_sku)]
            if not any(model.search(domain, limit=1) for model in search_models):
                return new_sku
        raise ValidationError("SKU limit reached.")

    @api.constrains("length", "width", "height")
    def _check_dimension_values(self) -> None:
        for product in self:
            fields_to_check = [product.length, product.width, product.height]
            for field_value in fields_to_check:
                if field_value and len(str(abs(field_value))) > 2:
                    raise ValidationError("Dimensions cannot exceed 2 digits.")

    @api.depends("mpn")
    def _compute_first_mpn(self) -> None:
        for product in self:
            list_of_mpns = product.get_list_of_mpns()
            if list_of_mpns:
                product.first_mpn = product.get_list_of_mpns()[0]
            else:
                product.first_mpn = ""

    def get_list_of_mpns(self) -> list[str]:
        for product in self:
            if not product.mpn or not product.mpn.strip():
                return []
            mpn_parts = re.split(r"[, ]", product.mpn)
            return [mpn.strip() for mpn in mpn_parts if mpn.strip()]

    @api.depends("images.image_1920")
    def _compute_image_count(self) -> None:
        for product in self:
            product.image_count = self.env["ir.attachment"].search_count(
                [
                    ("res_model", "=", product.images._name),
                    ("res_id", "in", product.images.ids),
                    ("res_field", "=", "image_1920"),
                    ("file_size", ">", 0),
                ]
            )

    @api.depends("message_ids")
    def _compute_has_recent_messages(self) -> None:
        for product in self:
            recent_messages = product.message_ids.filtered(
                lambda m: fields.Datetime.now() - m.create_date < timedelta(minutes=30)
                and m.subject
                and "Import Error" in m.subject
            )
            product.has_recent_messages = bool(recent_messages)

    def name_get(self) -> list[tuple[int, str]]:
        result = []
        for product in self:
            name = f"[{product.default_code}] {product.name or 'No Name Yet'}"
            result.append((product.id, name))
        return result

    @api.onchange("mpn")
    def _onchange_format_mpn_upper(self) -> None:
        for product in self.filtered(lambda p: p.mpn and p.mpn.upper() != p.mpn):
            product.mpn = product.mpn.upper()

    @api.onchange("bin")
    def _onchange_format_bin_upper(self) -> None:
        for product in self.filtered(lambda p: p.bin and p.bin.upper() != p.bin):
            product.bin = product.bin.upper()

    def _products_from_existing_products(self, field_name: str, field_value: str) -> list[dict[str, str]]:
        is_new_product = isinstance(self.id, models.NewId)
        if is_new_product:
            product_imports = self.search([(field_name, "=", field_value)])
        else:
            product_imports = self.search(
                [
                    (field_name, "=", field_value),
                    ("id", "!=", self.id),
                ]
            )
        product_templates = self.env["product.template"].search([(field_name, "=", field_value)])

        existing_products = {}
        for product in product_imports:
            product_to_add = {
                "default_code": product.default_code,
                "bin": product.bin,
                "condition": product.condition.id,
            }
            existing_products[product.default_code] = product_to_add

        for product in product_templates:
            product_to_add = {
                "default_code": product.default_code,
                "bin": product.bin,
                "condition": product.condition.id,
            }
            existing_products[product.default_code] = product_to_add

        return list(existing_products.values())

    def products_from_mpn_condition_new(self) -> list[dict[str, str]] | None:
        if self.mpn and self.condition.code == "new":
            existing_products = self._products_from_existing_products("mpn", self.first_mpn)
            existing_new_products = [product for product in existing_products if product["condition"] == "new"]
            if existing_new_products:
                return existing_new_products
        return None

    @api.model
    def _check_fields_and_images(self, product: "odoo.model.product_base") -> list[str]:
        missing_fields = self._check_missing_fields(product)
        missing_fields += self._check_missing_images_or_small_images(product.images)
        return missing_fields

    @api.model
    def _check_missing_fields(self, product: "odoo.model.product_base") -> list[str]:
        required_fields = [
            product._fields["default_code"].name,
            product._fields["name"].name,
            product._fields["website_description"].name,
            product._fields["standard_price"].name,
            product._fields["list_price"].name,
            product._fields["qty_available"].name,
            product._fields["bin"].name,
            product._fields["manufacturer"].name,
        ]

        missing_fields = [field for field in required_fields if not product[field]]

        return missing_fields

    @staticmethod
    def _check_missing_images_or_small_images(all_images: "odoo.model.product_image") -> list[str]:
        min_image_size = 50
        min_image_resolution = 1920
        missing_fields = []
        images_with_data = all_images.filtered(lambda i: i.image_1920)

        if not images_with_data:
            missing_fields.append("images")

        for image in images_with_data:
            if image.image_1920_file_size_kb < min_image_size:
                missing_fields.append(
                    f"Image ({image.index}) too small ({image.image_1920_file_size_kb}kB < {min_image_size}kB minimum size)"
                )
            if image.image_1920_width < min_image_resolution - 1 and image.image_1920_height < min_image_resolution - 1:
                missing_fields.append(
                    f"Image ({image.index}) too small ({image.image_1920_width}x{image.image_1920_height} < {min_image_resolution}x{min_image_resolution} minimum size)"
                )

        return missing_fields

    def _post_missing_data_message(self, products: "odoo.model.product_base") -> None:
        for product in products:
            missing_fields = self._check_fields_and_images(product)
            if missing_fields:
                missing_fields_display = ", ".join(missing_fields)
                product.message_post(
                    body=f"Missing data: {missing_fields_display}",
                    subject="Import Error",
                    subtype_id=self.env.ref("mail.mt_note").id,
                    partner_ids=[self.env.user.partner_id.id],
                )

        self.env.cr.commit()

    def import_to_products(self) -> None:
        if self._name in ["product.template", "product.product"]:
            raise UserError("This method is not available for Odoo base products.")

        not_ready_products = self.filtered(lambda p: self._check_fields_and_images(p))
        ready_products = self - not_ready_products

        if not_ready_products:
            self._post_missing_data_message(not_ready_products)
            if not ready_products:
                raise UserError("No products are ready to import.")
            message = f"{len(not_ready_products)} product(s) are not ready to import.  See the messages for details."
            self.env["bus.bus"]._sendone(
                self.env.user.partner_id,
                "simple_notification",
                {"title": "Import Warning", "message": message, "sticky": False},
            )

        templated_descriptions = self.env.context.get("website_description", {})
        templated_names = self.env.context.get("name", {})

        for product in ready_products:
            existing_products_with_mpn = product.products_from_mpn_condition_new()
            if existing_products_with_mpn:
                existing_products_display = [
                    f"{product['default_code']} - {product['bin']}" for product in existing_products_with_mpn
                ]
                raise UserError(
                    f"A product with the same MPN already exists.  Its SKU is/are {existing_products_display}"
                )
            existing_product = self.env["product.product"].search(
                [("default_code", "=", product.default_code)], limit=1
            )
            if existing_product:
                raise UserError(
                    f"A product with the same SKU already exists.  Its SKU is {existing_product.default_code}"
                )
            website_description = templated_descriptions.get(product.id, product.website_description)
            website_description = website_description.replace("{mpn}", " ".join(product.get_list_of_mpns()))

            name = templated_names.get(product.id, product.name)
            name = name.replace("{mpn}", " ".join(product.get_list_of_mpns()))

            new_product = self.env["product.product"].create(
                {
                    "default_code": product.default_code,
                    "mpn": product.mpn,
                    "manufacturer": product.manufacturer.id,
                    "bin": product.bin,
                    "name": name,
                    "website_description": website_description,
                    "part_type": product.part_type.id,
                    "weight": product.weight,
                    "list_price": product.list_price,
                    "standard_price": product.standard_price,
                    "condition": product.condition.id,
                    "detailed_type": "product",
                    "is_published": True,
                    "shopify_next_export": True,
                    "motor": product.motor.id,
                    "length": product.length,
                    "width": product.width,
                    "height": product.height,
                }
            )
            new_product.update_quantity(product.qty_available)

            sorted_images = product.images.sorted(key=lambda r: r.index)

            for image in sorted_images:
                if not image.image_1920:
                    continue

                self.env["product.image"].create(
                    {
                        "image_1920": image.image_1920,
                        "product_tmpl_id": new_product.product_tmpl_id.id,
                        "name": image.index,
                    }
                )
                image.unlink()
            product.action_archive()

    def print_bin_labels(self) -> None:
        unique_bins = [
            bin_location
            for bin_location in set(self.mapped("bin"))
            if bin_location and bin_location.strip().lower() not in ["", " ", "back"]
        ]
        unique_bins.sort()
        labels = []
        for product_bin in unique_bins:
            label_data = ["", "Bin: ", product_bin]
            label = self.generate_label_base64(label_data, barcode=product_bin)
            labels.append(label)

        self._print_labels(
            labels,
            odoo_job_type="product_label",
            job_name="Bin Label",
        )

    def print_product_labels(self, print_quantity: bool = False, printer_job_type: str = "product_label") -> None:
        labels = []
        for product in self:
            mpn = product.mpn.strip() if product.mpn else ""
            if "," in mpn:
                mpn = mpn.split(",")[0].strip()
            label_data = [
                f"SKU: {product.default_code}",
                "MPN: ",
                f"(SM){mpn}",
                f"{product.motor.motor_number or '       '}",
                product.condition.name if product.condition else "",
            ]
            quantity = getattr(product, "qty_available", 1) if print_quantity else 1
            label = self.generate_label_base64(
                label_data,
                bottom_text=self.wrap_text(product.name, 50),
                barcode=product.default_code,
                quantity=quantity,
            )
            labels.append(label)
        self._print_labels(
            labels,
            odoo_job_type=printer_job_type,
            job_name="Product Label",
        )
