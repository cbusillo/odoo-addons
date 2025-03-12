import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


# noinspection SqlResolve
def migrate(cr: Cursor, version: str) -> None:
    _logger.info("Post-migration: update images")
    env = util.env(cr)
    model_names = ["product.image", "product.import.image", "motor.image", "motor.product.image"]
    for model_name in model_names:
        model = env[model_name]
        for image in model.search([]):
            image._compute_image_details()

    _logger.info("Post-migration: updated images")
