import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


# noinspection SqlResolve
def migrate(cr: Cursor, version: str) -> None:
    _logger.info("Pre-migration: Renaming product fields")

    util.rename_field(cr, "motor", "icon", "image_icon")

    util.rename_field(cr, "motor.product", "quantity", "qty_available")
    util.rename_field(cr, "motor.product", "price", "list_price")
    util.rename_field(cr, "motor.product", "cost", "standard_price")
    util.rename_field(cr, "motor.product", "product_type", "part_type")
    util.rename_field(cr, "motor.product", "icon", "image_icon")

    util.rename_field(cr, "product.import", "quantity", "qty_available")
    util.rename_field(cr, "product.import", "price", "list_price")
    util.rename_field(cr, "product.import", "cost", "standard_price")
    util.rename_field(cr, "product.import", "product_type", "part_type")
    util.rename_field(cr, "product.import", "icon", "image_icon")

    util.rename_field(cr, "product.template", "icon", "image_icon")

    util.rename_field(cr, "motor.product.template", "product_type", "part_type")

    _logger.info("Pre-migration: Renamed product fields")
