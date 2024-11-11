import re

import odoo
from odoo import api, exceptions, fields, models, _


class MotorDismantleResult(models.Model):
    _name = "motor.dismantle.result"
    _description = "Motor Dismantle Result"

    name = fields.Char(required=True)


class MotorProductTemplateCondition(models.Model):
    _name = "motor.product.template.condition"
    _description = "Motor Product Template Condition"
    _inherit = ["motor.test.condition.mixin"]

    template = fields.Many2one("motor.product.template", ondelete="cascade")
    excluded_by_tests = fields.One2many("motor.product", "template", string="Excluded by Tests")


class MotorProductTemplate(models.Model):
    _name = "motor.product.template"
    _description = "Motor Product Template"
    _order = "sequence, id"

    name = fields.Char(required=True)

    stroke = fields.Many2many("motor.stroke")
    configurations = fields.Many2many("motor.configuration")
    manufacturers = fields.Many2many("product.manufacturer", domain=[("is_motor_manufacturer", "=", True)])
    excluded_by_parts = fields.Many2many("motor.part.template")
    excluded_by_tests = fields.One2many("motor.product.template.condition", "template")
    is_quantity_listing = fields.Boolean(default=False)
    include_year_in_name = fields.Boolean(default=True)
    include_hp_in_name = fields.Boolean(default=True, string="Include HP in Name")
    include_model_in_name = fields.Boolean(default=True)
    include_oem_in_name = fields.Boolean(default=True, string="Include OEM in Name")

    part_type = fields.Many2one("product.type", index=True)
    qty_available = fields.Float()
    bin = fields.Char()
    weight = fields.Float()
    sequence = fields.Integer(default=10, index=True)
    website_description = fields.Html(string="HTML Description")

    @api.model
    def get_template_tags_list(self) -> list[str]:
        tag_keys = list(self.get_template_tags().keys())
        tag_keys += ["mpn"]
        sorted_tags = sorted(tag_keys)
        return sorted_tags

    def get_template_tags(self) -> dict[str, str]:
        all_tags = self.get_template_tags_from_motor_model()
        all_tags.update(self.get_template_tags_from_test_tags())
        return all_tags

    def get_template_tags_from_test_tags(self) -> dict[str, str]:
        tests = self.env["motor.test.template"].search([("tag", "!=", "")])
        return {test.tag: test.tag_value for test in tests}

    def get_template_tags_from_motor_model(self) -> dict[str, str]:
        template_tags = {}
        fields_to_skip = ("uid", "stage", "is_")
        motor_model = self.env["motor"]
        for field_name, field in motor_model._fields.items():
            if any(skip in field_name for skip in fields_to_skip):
                continue
            if isinstance(field, (fields.Selection, fields.Selection, fields.Many2one, fields.Float, fields.Text)):
                template_tags[f"motor_{field_name}"] = field_name

        return template_tags


class MotorProductImage(models.Model):
    _name = "motor.product.image"
    _inherit = ["image.mixin"]
    _description = "Motor Product Images"

    index = fields.Integer(index=True, required=True, default=lambda self: self._get_next_index())
    product = fields.Many2one("motor.product", ondelete="cascade", required=True, index=True)

    def _get_next_index(self) -> int:
        last_index = self.search([("product", "=", self.product.id)], order="index desc", limit=1).index
        return (last_index or 0) + 1


class MotorProduct(models.Model):
    _name = "motor.product"
    _inherit = ["product.base", "mail.thread", "mail.activity.mixin"]
    _description = "Motor Product"
    _order = "sequence, is_listable desc, part_type_name, id"

    images = fields.One2many("motor.product.image", "product")

    template = fields.Many2one("motor.product.template", required=True, ondelete="restrict", readonly=True)
    part_type = fields.Many2one(related="template.part_type", store=True)
    computed_name = fields.Char(compute="_compute_name", store=True)
    template_name = fields.Char(related="template.name", string="Template Name")
    is_qty_listing = fields.Boolean(related="template.is_quantity_listing")

    reference_product = fields.Many2one("product.template", compute="_compute_reference_product", store=True)

    sequence = fields.Integer(related="template.sequence", index=True, store=True)

    dismantle_notes = fields.Text()
    template_name_with_dismantle_notes = fields.Char(compute="_compute_template_name_with_dismantle_notes", store=False)
    dismantle_results = fields.Many2one(comodel_name="motor.dismantle.result", ondelete="restrict")

    is_dismantled = fields.Boolean(default=False, tracking=True)
    is_dismantled_qc = fields.Boolean(default=False)
    is_cleaned = fields.Boolean(default=False)
    is_cleaned_qc = fields.Boolean(default=False)
    is_picture_taken = fields.Boolean(default=False)
    is_pictured = fields.Boolean(default=False)
    is_pictured_qc = fields.Boolean(default=False)
    is_ready_to_list = fields.Boolean(compute="_compute_ready_to_list", store=True)

    def write(self, vals: "odoo.values.motor_product") -> bool:
        qc_reset_fields = {
            "is_dismantled",
            "is_cleaned",
            "is_pictured",
        }
        ui_refresh_fields = {
            "is_listable",
            "is_dismantled",
            "is_dismantled_qc",
            "is_cleaned",
            "is_cleaned_qc",
            "is_pictured",
            "is_pictured_qc",
            "bin",
            "weight",
        }

        for field in qc_reset_fields:
            if field in vals and not vals[field]:
                vals[f"{field}_qc"] = False

        if "is_pictured" in vals and vals["is_pictured"] and not self.images:
            vals["is_pictured"] = False
            self.env["bus.bus"]._sendone(
                self.env.user.partner_id,
                "simple_notification",
                {"title": "Missing Pictures", "message": "Please upload pictures before proceeding.", "sticky": False},
            )

        if "is_pictured" in vals and vals["is_pictured"]:
            vals["is_picture_taken"] = True

        if "is_dismantled" in vals and vals["is_dismantled"]:
            message_text = f"Product '{self.template_name}' dismantled"
            self.motor.message_post(body=message_text, message_type="comment", subtype_xmlid="mail.mt_note")

        result = super(MotorProduct, self).write(vals)

        if "images" in vals:
            for product in self:
                if product.image_count < 1:
                    product.is_pictured = False
                    product.is_pictured_qc = False

        if any(field in vals for field in ui_refresh_fields):
            for product in self:
                product.motor.notify_changes()
        return result

    def import_to_products(self) -> None:
        products = self.filtered(lambda p: p.is_listable and p.is_ready_to_list)
        if not products:
            raise exceptions.UserError(_("No products to import."))

        products_with_template = products.with_context(
            website_description={p.id: p.replace_template_tags(p.website_description) for p in products},
            name={p.id: p.replace_template_tags(p.name) for p in products},
        )
        super(MotorProduct, products_with_template).import_to_products()

    @api.depends("mpn")
    def _compute_reference_product(self) -> None:
        for motor_product in self:
            if not motor_product.mpn:
                motor_product.reference_product = False
                continue
            products = self.env["product.template"].search([("mpn", "!=", False)])
            product_mpns = motor_product.get_list_of_mpns()
            matching_products = products.filtered(lambda p: any(mpn.lower() in p.mpn.lower() for mpn in product_mpns))
            latest_product = max(matching_products, key=lambda p: p.create_date, default=None)
            motor_product.reference_product = latest_product

    @api.depends("template_name", "dismantle_notes")
    def _compute_template_name_with_dismantle_notes(self) -> None:
        for product in self:
            product.template_name_with_dismantle_notes = (
                f"{product.template_name}\n({product.dismantle_notes})"
                if product.dismantle_notes
                else product.template_name
            )

    @api.depends("name", "computed_name", "default_code")
    def _compute_display_name(self) -> None:
        for product in self:
            product.display_name = f"{product.default_code} - {product.name or product.computed_name}"

    @api.depends(
        "motor.manufacturer.name",
        "template.name",
        "mpn",
        "motor.year",
        "motor.horsepower",
        "template.include_year_in_name",
        "template.include_hp_in_name",
        "template.include_model_in_name",
        "template.include_oem_in_name",
    )
    def _compute_name(self) -> None:
        for product in self:
            name_parts = [
                product.motor.year if product.template.include_year_in_name else None,
                product.motor.manufacturer.name if product.motor.manufacturer else None,
                (product.motor.get_horsepower_formatted() if product.template.include_hp_in_name else None),
                product.motor.stroke.name,
                "Outboard",
                product.template.name,
                product.first_mpn if product.template.include_model_in_name else None,
                "OEM" if product.template.include_oem_in_name else None,
            ]
            new_computed_name = " ".join(part for part in name_parts if part)
            if not product.name or product.name == product.computed_name:
                product.name = new_computed_name
            product.computed_name = new_computed_name

    @api.depends(
        "is_dismantled",
        "is_dismantled_qc",
        "is_cleaned",
        "is_cleaned_qc",
        "is_pictured",
        "is_pictured_qc",
        "bin",
        "weight",
    )
    def _compute_ready_to_list(self) -> None:
        for product in self:
            product.is_ready_to_list = all(
                [
                    product.is_dismantled,
                    product.is_dismantled_qc,
                    product.is_cleaned,
                    product.is_cleaned_qc,
                    product.is_pictured,
                    product.is_pictured_qc,
                    product.bin,
                    product.weight,
                ]
            )

    def reset_name(self) -> None:
        for product in self:
            product.name = ""
            product._compute_name()

    def replace_template_tags(self, templated_content: str) -> str:
        if not templated_content:
            return ""

        used_tags = re.findall(r"{(.*?)}", templated_content)
        template_tags = self.template.get_template_tags()
        values = {}

        for tag in used_tags:
            tag = tag.lower()
            if tag not in template_tags:
                continue

            tag_value = template_tags.get(tag, tag)
            value = self._resolve_tag_value(tag_value) or ""
            values[tag] = str(value)

        return self._apply_tag_values(templated_content, values)

    def _resolve_tag_value(self, tag_value: str) -> str | list:
        if tag_value.startswith("tests."):
            test_index = int(tag_value.split(".")[1])
            test = self.motor.tests.filtered(lambda t: t.template.id == test_index)[0]
            return (
                test.selection_result.display_value or test.selection_result.value
                if test.selection_result
                else test.computed_result
            )

        value = self.motor
        for field in tag_value.split("."):
            value = getattr(value, field, "")
        return value if not isinstance(value, list) else ", ".join(str(v) for v in value)

    @staticmethod
    def _apply_tag_values(content: str, values: dict[str, str]) -> str:
        for tag, value in values.items():
            content = content.replace(f"{{{tag}}}", value).replace("  ", " ")
        return content
