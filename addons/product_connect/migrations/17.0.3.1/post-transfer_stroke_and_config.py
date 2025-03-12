import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


def migrate(cr: Cursor, version: str) -> None:
    env = util.env(cr)
    model_motor = env["motor"]
    stroke_model = env["motor.stroke"]
    config_model = env["motor.configuration"]

    _logger.info("Post-migration: Updating motor records with new stroke and configuration IDs")

    # noinspection SqlResolve
    cr.execute("SELECT motor_id, old_stroke, old_config FROM temp_motor_data")
    data = cr.fetchall()

    for motor_id, old_stroke, old_config in data:
        stroke = stroke_model.search([("code", "=", old_stroke)], limit=1)
        config = config_model.search([("code", "=", old_config)], limit=1)

        motor = model_motor.browse(motor_id)
        if stroke:
            motor.write({"stroke": stroke.id})
        if config:
            motor.write({"configuration": config.id})

    cr.execute("DROP TABLE IF EXISTS temp_motor_data")

    _logger.info("Post-migration completed successfully")
