import logging

from odoo.sql_db import Cursor
from odoo.upgrade.util import rename_field

_logger = logging.getLogger(__name__)


def migrate(cr: Cursor, _version: str) -> None:
    _logger.info("Running post-migration script.")

    # noinspection SqlResolve
    cr.execute("DELETE FROM product_import_image WHERE product_id IS NULL")
    _logger.info(f"Deleted {cr.rowcount} records with NULL 'product_id' values.")
    rename_field(cr, "product.import.image", "product_id", "product")

    cr.connection.commit()
    _logger.info("Removed records with NULL 'product' values.")
