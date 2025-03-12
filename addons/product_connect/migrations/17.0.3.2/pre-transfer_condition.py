import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


# noinspection SqlResolve
def migrate(cr: Cursor, version: str) -> None:
    _logger.info("Pre-migration: Storing condition data")

    cr.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS temp_product_data (
            product_id INT,
            old_condition VARCHAR
        )
    """
    )

    cr.execute(
        """
        INSERT INTO temp_product_data (product_id, old_condition)
        SELECT id, condition FROM product_template
    """
    )

    util.remove_field(cr, "product.template", "condition")

    cr.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS temp_product_import_data (
            product_id INT,
            old_condition VARCHAR
        )
    """
    )

    cr.execute(
        """
        INSERT INTO temp_product_import_data (product_id, old_condition)
        SELECT id, condition FROM product_import
    """
    )

    util.remove_field(cr, "product.import", "condition")

    _logger.info("Pre-migration: Finished storing condition data")
