import base64
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Self

import odoo
import qrcode
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError, UserError

from ..utils import constants


class Motor(models.Model):
    _name = "motor"
    _inherit = ["label.mixin"]
    _description = "Motor Information"
    _order = "id desc"

    # Basic Info
    active = fields.Boolean(default=True)
    motor_number = fields.Char()
    location = fields.Char()
    technician = fields.Many2one(
        "res.users",
        string="Tech Name",
        domain="['|', ('id', '=', technician), '&', ('is_technician', '=', True), ('active', '=', True)]",
        ondelete="restrict",
    )
    vendor = fields.Many2one("res.partner")
    lot_id = fields.Char(size=5)
    manufacturer = fields.Many2one("product.manufacturer", domain="[('is_motor_manufacturer', '=', True)]")
    horsepower = fields.Float(digits=(3, 1), string="HP")
    horsepower_formatted = fields.Char(compute="_compute_horsepower_formatted")
    stroke = fields.Many2one("motor.stroke")
    configuration = fields.Many2one("motor.configuration")
    model = fields.Char()
    sub_model = fields.Char()
    serial_number = fields.Char()

    @api.model
    def _get_years(self) -> list[tuple[str, str]]:
        return [(str(year), str(year)) for year in range(fields.Date.today().year + 1, 1960, -1)]

    year = fields.Selection(_get_years, string="Model Year")
    color = fields.Many2one("product.color", domain="[('applicable_tags.name', '=', 'Motors')]")
    cost = fields.Float()

    # from tests
    hours = fields.Float(compute="_compute_hours")
    shaft_length = fields.Char(compute="_compute_shaft_length")

    is_tag_readable = fields.Selection(constants.YES_NO_SELECTION, default=constants.YES)
    notes = fields.Text()
    has_notes = fields.Boolean(compute="_compute_has_notes", store=True)
    images = fields.One2many("motor.image", "motor")
    image_count = fields.Integer(compute="_compute_image_count")
    image_icon = fields.Binary(compute="_compute_icon", store=True)
    parts = fields.One2many("motor.part", "motor")
    missing_parts = fields.One2many("motor.part", "motor", domain=[("is_missing", "=", True)])
    missing_parts_names = fields.Char(compute="_compute_missing_parts_names", store=True)
    tests = fields.One2many("motor.test", "motor")
    test_sections = fields.One2many("motor.test.section", "motor")
    basic_tests = fields.One2many("motor.test", "motor", domain=[("template.stage", "=", "basic")])
    extended_tests = fields.One2many("motor.test", "motor", domain=[("template.stage", "=", "extended")])

    cylinders = fields.One2many("motor.cylinder", "motor")

    compression_formatted_html = fields.Html(compute="_compute_compression_formatted_html")
    hide_compression_page = fields.Boolean(compute="_compute_hide_compression_page", store=True)
    products = fields.One2many("motor.product", "motor")
    products_with_reference_product = fields.Many2many(
        "motor.product",
        "motor_product_with_reference_product_rel",
        "motor_id",
        "product_id",
        compute="_compute_products_with_reference",
        store=True,
    )

    products_to_dismantle = fields.One2many(
        "motor.product",
        "motor",
        domain=[("is_listable", "=", True)],
    )

    products_to_clean = fields.One2many(
        "motor.product",
        "motor",
        domain=[
            ("is_listable", "=", True),
            ("is_dismantled", "=", True),
            ("is_dismantled_qc", "=", True),
        ],
    )

    products_to_picture = fields.One2many(
        "motor.product",
        "motor",
        domain=[
            ("is_listable", "=", True),
            ("is_dismantled", "=", True),
            ("is_dismantled_qc", "=", True),
            ("is_cleaned", "=", True),
            ("is_cleaned_qc", "=", True),
        ],
    )

    products_to_stock = fields.One2many(
        "motor.product",
        "motor",
        domain=[
            ("is_listable", "=", True),
            ("is_dismantled", "=", True),
            ("is_dismantled_qc", "=", True),
            ("is_cleaned", "=", True),
            ("is_cleaned_qc", "=", True),
            ("is_pictured", "=", True),
            ("is_pictured_qc", "=", True),
        ],
    )

    stage = fields.Selection(constants.MOTOR_STAGE_SELECTION, default="basic_info", required=True)

    @api.model_create_multi
    def create(self, vals_list: list["odoo.values.motor"]) -> Self:
        vals_list = [self._sanitize_vals(vals) for vals in vals_list]

        motors = super().create(vals_list)
        for motor in motors:
            if motor.id > 999999:
                raise ValidationError(_("Motor number cannot exceed 999999."))
            motor.motor_number = f"M-{str(motor.id).zfill(6)}"
            motor._create_default_images(motor)
            motor._compute_compression()
            motor._create_motor_parts()
            motor._create_motor_tests()

        return motors

    def write(self, vals: "odoo.values.motor") -> bool:
        if self.env.context.get("_stage_updating"):
            return super().write(vals)
        vals = self._sanitize_vals(vals)

        result = super().write(vals)
        if "configuration" in vals:
            self._compute_compression()
        for motor in self.with_context(_stage_updating=True):
            motor._update_stage()
        return result

    @api.depends("products.reference_product", "products.reference_product.image_256")
    def _compute_products_with_reference(self) -> None:
        for motor in self:
            reference_products = motor.products.filtered(
                lambda p: p.reference_product and p.reference_product.image_256
            )

            if reference_products != motor.products_with_reference_product:
                motor.products_with_reference_product = reference_products

    def _compute_image_count(self) -> None:
        for motor in self:
            motor.image_count = len([image for image in motor.images if image.image_1920])

    def _compute_compression_formatted_html(self) -> None:
        for motor in self:
            lines = [f"Cylinder: {c.cylinder_number} Compression: {c.compression_psi} PSI" for c in motor.cylinders]
            motor.compression_formatted_html = "<br/>".join(lines)

    def _compute_missing_parts_names(self) -> None:
        for motor in self:
            missing_parts_names = ", ".join(part.name for part in motor.missing_parts if part.name)
            motor.missing_parts_names = missing_parts_names

    def _compute_shaft_length(self) -> None:
        for motor in self:
            shaft_length = motor.tests.filtered(
                lambda t: "shaft" in t.template.name.lower() and "length" in t.template.name.lower()
            )
            motor.shaft_length = shaft_length.selection_result if shaft_length else ""

    def _compute_hours(self) -> None:
        for motor in self:
            hours = motor.tests.filtered(
                lambda t: "engine" in t.template.name.lower() and "hours" in t.template.name.lower()
            )
            motor.hours = hours.numeric_result if hours else 0

    @api.depends("notes")
    def _compute_has_notes(self) -> None:
        for motor in self:
            motor.has_notes = bool(motor.notes)

    @api.depends("images")
    def _compute_icon(self) -> None:
        for motor in self:
            motor.image_icon = motor.images[0].image_128 if motor.images else False

    @api.depends("horsepower")
    def _compute_horsepower_formatted(self) -> None:
        for motor in self:
            motor.horsepower_formatted = motor.get_horsepower_formatted()

    @api.depends("motor_number", "manufacturer", "model", "year", "serial_number", "horsepower")
    def _compute_display_name(self) -> None:
        for motor in self:
            serial_number = f" - {motor.serial_number}" if motor.serial_number else None

            name_parts = [
                motor.motor_number,
                motor.year,
                motor.manufacturer.name,
                motor.get_horsepower_formatted(),
                motor.model,
                serial_number,
            ]
            name = " ".join(part for part in name_parts if part)

            if name:
                motor.display_name = name
            else:
                motor.display_name = "New Motor"

    @api.depends("parts.is_missing", "parts.template.hide_compression_page")
    def _compute_hide_compression_page(self) -> None:
        for motor in self:
            hide_parts = motor.parts.filtered(lambda p: p.is_missing and p.template.hide_compression_page)
            motor.hide_compression_page = bool(hide_parts)

    def generate_qr_code(self) -> str:
        qr_code = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=20,
        )
        qr_code.add_data(self.motor_number)
        qr_code.make()

        qr_image = qr_code.make_image(fill_color="black", back_color="white")

        with BytesIO() as qr_image_buffer:
            qr_image.save(qr_image_buffer)
            qr_image_base64 = base64.b64encode(qr_image_buffer.getvalue()).decode()

        return qr_image_base64

    def get_horsepower_formatted(self) -> str:
        if not self.horsepower:
            return ""

        if self.horsepower.is_integer():
            return f"{int(self.horsepower)} HP"
        else:
            return f"{self.horsepower} HP"

    @api.constrains("horsepower")
    def _check_horsepower(self) -> None:
        for motor in self:
            if motor.horsepower < 0.0 or motor.horsepower > 600.0:
                raise ValidationError(_("Horsepower must be between 0 and 600."))

    @api.constrains("location")
    def _check_unique_location(self) -> None:
        for motor in self:
            if not motor.location:
                continue
            existing_motor = self.search([("location", "=", motor.location), ("id", "!=", motor.id)], limit=1)
            if existing_motor:
                raise ValidationError(
                    _(f"Motor {existing_motor.motor_number} with location '{motor.location}' already exists.")
                )

    @staticmethod
    def _sanitize_vals(vals: "odoo.values.motor") -> "odoo.values.motor":
        if "year" in vals and vals["year"]:
            vals["year"] = "".join(char for char in vals["year"] if char.isdigit())
        if "model" in vals and vals["model"]:
            vals["model"] = vals["model"].upper()
        if "serial_number" in vals and vals["serial_number"]:
            vals["serial_number"] = vals["serial_number"].upper()
        return vals

    def _create_motor_tests(self) -> None:
        test_templates = self.env["motor.test.template"].search([])
        test_vals = []
        for template in test_templates:
            test_vals.append(
                {
                    "motor": self.id,
                    "template": template.id,
                }
            )
        if test_vals:
            self.env["motor.test"].create(test_vals)

    def _create_motor_parts(self) -> None:
        part_templates = self.env["motor.part.template"].search([])
        part_vals = []
        for template in part_templates:
            part_vals.append(
                {
                    "motor": self.id,
                    "template": template.id,
                }
            )
        if part_vals:
            self.env["motor.part"].create(part_vals)

    def create_motor_products(self) -> None:
        product_templates = self.env["motor.product.template"].search([])
        current_product_ids = set(self.products.ids)  # Existing product IDs related to this motor

        for product_template in product_templates:
            if product_template.stroke and self.stroke not in product_template.stroke:
                continue
            if product_template.configuration and self.configuration not in product_template.configuration:
                continue
            if product_template.manufacturers and self.manufacturer not in product_template.manufacturers:
                continue

            excluded_parts_ids = product_template.excluded_parts.mapped("id")
            if set(self.parts.mapped("template.id")) & set(excluded_parts_ids):
                continue

            excluded_tests_ids = product_template.excluded_tests.mapped("id")
            if set(self.tests.mapped("template.id")) & set(excluded_tests_ids):
                continue

            existing_product = self.products.filtered(lambda p: p.template == product_template)

            if existing_product:
                current_product_ids.discard(existing_product.id)
            else:
                condition_id = self.env.ref("product_connect.product_condition_used").id
                self.products.create(
                    {
                        "motor": self.id,
                        "template": product_template.id,
                        "qty_available": product_template.qty_available or 1,
                        "bin": product_template.bin,
                        "weight": product_template.weight,
                        "condition": condition_id,
                        "manufacturer": self.manufacturer.id,
                    }
                )

        if current_product_ids:
            self.products.filtered(lambda p: p.id in current_product_ids).unlink()

    def _get_cylinder_count(self) -> int:
        match = re.search(r"\d+", self.configuration.name)
        if match:
            return int(match.group())
        return 0

    def _compute_compression(self) -> None:
        for motor in self:

            desired_cylinders = motor._get_cylinder_count()
            current_cylinders = motor.cylinders.mapped("cylinder_number")

            excessive_cylinders = motor.cylinders.filtered(lambda x: x.cylinder_number > desired_cylinders)
            if excessive_cylinders:
                excessive_cylinders.unlink()

            # Add missing cylinders
            existing_cylinder_numbers = set(current_cylinders)
            for i in range(1, desired_cylinders + 1):
                if i not in existing_cylinder_numbers:
                    self.cylinders.create(
                        {
                            "motor": motor.id,
                            "cylinder_number": i,
                            "compression_psi": 0,
                        }
                    )

    def _create_default_images(self, motor: Self) -> None:
        image_names = constants.MOTOR_IMAGE_NAME_AND_ORDER
        for name in image_names:
            self.images.create(
                {
                    "motor": motor.id,
                    "name": name,
                }
            )

    def _update_stage(self) -> None:
        stages_with_required_fields = {
            "basic_testing": [
                "motor_number",
                "manufacturer",
                "stroke",
                "configuration",
                "color",
            ],
            "extended_testing": [
                # "engine_ecu_hours",
                # "shaft_length",
                # "compression_numbers",
                # "fuel_pump_status",
                # "trim_tilt_unit_status",
                # "lower_unit_fluid_condition",
                # "lower_unit_pressure_status",
            ],
            "finalization": [
                # "lower_unit_gear_engages_when_removed",
            ],
        }

        for stage, stage_fields in stages_with_required_fields.items():
            if all(getattr(self, f, None) for f in stage_fields):
                self.stage = stage
            else:
                break

    def download_zip_of_images(self) -> dict[str, str]:
        temp_path = Path(tempfile.mkdtemp())
        zip_path = temp_path / f"{self.motor_number} {datetime.now().strftime('%Y-%m-%d %H-%M')}.zip"
        with zipfile.ZipFile(zip_path, "w") as zip_file:
            for motor in self:
                for image in motor.images:
                    if not image.image_1920:
                        continue
                    filename = f"{motor.motor_number} {image.name}.jpg"
                    file_path = temp_path / filename
                    with open(file_path, "wb") as image_file:
                        image_file.write(base64.b64decode(image.image_1920))
                    zip_file.write(file_path, filename)
                    file_path.unlink()

        with open(zip_path, "rb") as zip_file:
            zip_data = base64.b64encode(zip_file.read())

        attachment = self.env["ir.attachment"].create(
            {
                "name": zip_path.name,
                "datas": zip_data,
                "type": "binary",
                "mimetype": "application/zip",
            }
        )

        download_url = f"/web/binary/download_single?attachment_id={attachment.id}"
        shutil.rmtree(temp_path)

        return {
            "type": "ir.actions.act_url",
            "url": download_url,
            "target": "self",
        }

    def apply_cost(self) -> None:
        products = self.products.filtered(lambda p: p.is_listable and p.qty_available > 0)
        total_price = sum(record.list_price * record.qty_available for record in products)

        for product in products:
            cost_proportion = (product.list_price * product.qty_available) / total_price if total_price else 0
            product.standard_price = (cost_proportion * self.cost) / product.qty_available

    def import_to_products(self) -> None:
        self.products.import_to_products()

    def print_motor_product_labels(self) -> None:
        products = self.products.filtered(lambda p: p.is_listable and p.qty_available > 0)
        if not products:
            raise UserError(_("No products to print labels for."))

        products.print_product_labels(print_quantity=True)

    def print_motor_pull_list(self) -> None:
        products = self.products.filtered(lambda p: p.is_listable and p.qty_available > 0)
        if not products:
            raise UserError(_("No products to print pull list for."))

        report_name = "product_connect.report_motorproductpulllist"
        report_object = self.env["ir.actions.report"]._get_report_from_name(report_name)
        pdf_data, _type = report_object._render_qweb_pdf(report_name, res_ids=products.ids)

        self._print_labels(pdf_data, odoo_job_type="pull_list", job_name="Motor Pull List", copies=2)

    def notify_changes(self) -> None:
        self.ensure_one()
        channel = f"motor_{self.id}"
        message = {
            "type": "motor_product_update",
        }
        self.env["bus.bus"]._sendone(channel, "notification", message)

    def print_motor_labels(self, printer_job_type: str = "motor_label") -> None:
        report_name = "product_connect.report_motortemplatelabel4x2noprice"
        report_object = self.env["ir.actions.report"]._get_report_from_name(report_name)
        pdf_data, _ = report_object._render_qweb_pdf(report_name, res_ids=self.ids)

        self._print_labels(pdf_data, odoo_job_type=printer_job_type, job_name="Motor Label")
