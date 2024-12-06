import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


# noinspection SqlResolve,PyUnresolvedReferences
def migrate(cr: Cursor, version: str) -> None:
    env = util.env(cr)
    product_template = env["product.template"]
    product_import = env["product.import"]
    product_condition = env["product.condition"]

    _logger.info("Post-migration: Updating product and product_import records with new condition IDs")

    # noinspection SqlResolve
    cr.execute("SELECT product_id, old_condition FROM temp_product_data")
    data = cr.fetchall()

    for product_id, old_config in data:
        condition = product_condition.search([("code", "=", old_config)], limit=1)
        if condition:
            product = product_template.browse(product_id)
            product.condition = condition

    cr.execute("DROP TABLE IF EXISTS temp_product_data")

    # noinspection SqlResolve
    cr.execute("SELECT product_id, old_condition FROM temp_product_import_data")
    data = cr.fetchall()

    for product_id, old_config in data:
        condition = product_condition.search([("code", "=", old_config)], limit=1)
        if condition:
            product = product_import.browse(product_id)
            product.condition = condition

    _logger.info("Post-migration completed successfully")
