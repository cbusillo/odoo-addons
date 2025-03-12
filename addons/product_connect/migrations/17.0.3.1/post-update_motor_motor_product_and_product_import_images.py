import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)

MODELS = ["motor.image", "motor.product.image", "product.import.image"]


def migrate(cr: Cursor, version: str) -> None:
    env = util.env(cr)

    for model_name in MODELS:
        model = env[model_name]
        parent_model_name = model_name.rsplit(".", 1)[0]
        if parent_model_name:
            parent_model = env[parent_model_name]
            if "icon" in parent_model._fields:
                records = parent_model.search([])

                records._compute_icon()

        records = model.search([])
        for record in records:
            record.image_1920 = record.image_1920
