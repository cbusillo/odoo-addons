import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


# noinspection SqlResolve
def migrate(cr: Cursor, version: str) -> None:
    _logger.info("Pre-migration: Renaming product fields")

    util.rename_field(cr, "motor.product", "description", "sales_description")
    util.rename_field(cr, "product.import", "description", "sales_description")

    _logger.info("Pre-migration: Renamed product fields")
