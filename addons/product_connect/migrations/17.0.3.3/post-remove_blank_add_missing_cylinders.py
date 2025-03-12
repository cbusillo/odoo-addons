import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


# noinspection SqlResolve
def migrate(cr: Cursor, version: str) -> None:
    _logger.info("Post-migration: removing bad cylinders and adding missing'")
    env = util.env(cr)

    motors = env["motor"].search([])
    for motor in motors:
        motor._compute_compression()
        for cylinder in motor.cylinders:
            if cylinder.cylinder_number is None or cylinder.cylinder_number == 0:
                motor.cylinders -= cylinder

    cr.execute("DELETE FROM motor_cylinder WHERE cylinder_number IS NULL OR cylinder_number = 0")

    _logger.info("Post-migration: Fixed 'motor.cylinder' records")
