import logging

from odoo import fields
from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


def migrate(cr: Cursor, _version: str) -> None:
    _logger.info(f"Running migration script: {__name__}")
    env = util.env(cr)

    model_motor_image = env["motor.image"]
    # noinspection PyUnresolvedReferences,PyProtectedMember
    if "image_data" not in model_motor_image._fields:
        _logger.info("Adding image_data field to motor.image model")
        # noinspection PyProtectedMember
        env["motor.image"]._add_field("image_data", fields.Binary("Image Data"))

    records = env["motor.image"].search([])
    _logger.info("Found %d records in motor.image model", len(records))

    for record in records:
        if record.image_data and not record.image_1920:
            _logger.info("Migrating image_data to image_1920 for record ID: %d", record.id)
            record.image_1920 = record.image_data
            record.image_data = False

    _logger.info("Migration script completed")
