import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from odoo import models, fields, api
from odoo.tools import config

_logger = logging.getLogger(__name__)


class ImageMixin(models.AbstractModel):
    _description = "Image Mixin"
    _inherit = "image.mixin"

    attachment = fields.Many2one("ir.attachment", compute="_compute_attachment", store=True)
    image_1920_file_size = fields.Integer(related="attachment.file_size", store=True)
    image_1920_file_size_kb = fields.Float(string="kB", compute="_compute_file_size_kb", store=True)
    image_1920_width = fields.Integer(compute="_compute_image_dimensions", store=True)
    image_1920_height = fields.Integer(compute="_compute_image_dimensions", store=True)
    image_1920_resolution = fields.Char(compute="_compute_image_dimensions", store=True, string="Image Res")
    index = fields.Integer()

    @api.depends("image_1920")
    def _compute_attachment(self) -> None:
        for record in self:
            record.attachment = self.env["ir.attachment"].search(
                [
                    ("res_model", "=", self._name),
                    ("res_id", "=", record.id),
                    ("res_field", "=", "image_1920"),
                ],
                limit=1,
            )

    @api.depends("attachment.file_size")
    def _compute_file_size_kb(self) -> None:
        for image in self:
            image.image_1920_file_size_kb = round(image.image_1920_file_size / 1024, 2)

    @api.depends("attachment.store_fname")
    def _compute_image_dimensions(self) -> None:
        for record in self:
            db_name = self.env.cr.dbname
            filestore_path = Path(config.filestore(db_name))
            if not image.attachment.store_fname:
                _logger.warning(f"Image: {image} has no store_fname")
                self._reset_image_details(image)
            if not record.attachment.store_fname:
                self._reset_image_details(record)
                continue
            image_path = filestore_path / Path(record.attachment.store_fname)

            try:
                with Image.open(image_path) as img:
                    width, height = img.size
                    record.image_1920_width = width
                    record.image_1920_height = height
                    record.image_1920_resolution = f"{width}x{height}"
            except FileNotFoundError:
                _logger.warning(f"Image: {record} file not found\n {image_path}")
                self._reset_image_details(record)
            except UnidentifiedImageError as e:
                if "svg" in record.attachment.mimetype:
                    _logger.info(f"Image: {record.attachment} is an SVG")
                    self._reset_image_details(record)
                else:
                    _logger.warning(f"Image: {record.attachment} unidentified image {e}")
                    raise e

    @staticmethod
    def _reset_image_details(image) -> None:
        image.image_1920_file_size = None
        image.image_1920_file_size_kb = None
        image.image_1920_width = None
        image.image_1920_height = None
        image.image_1920_resolution = None

    def action_open_full_image(self) -> dict:
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/image?model={self._name}&id={self.id}&field=image_1920",
            "target": "new",
        }
