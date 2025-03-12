import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


def migrate(cr: Cursor, _version: str) -> None:
    _logger.info(f"Running migration script: {__name__}")

    util.rename_field(cr, "product.manufacturer", "is_engine_manufacturer", "is_motor_manufacturer")
    util.remove_field(cr, "product.manufacturer", "is_engine_manufacturer")

    _logger.info("Migration script completed")
