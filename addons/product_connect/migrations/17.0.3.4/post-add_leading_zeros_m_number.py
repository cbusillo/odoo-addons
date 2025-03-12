import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


# noinspection SqlResolve
def migrate(cr: Cursor, version: str) -> None:
    _logger.info("Post-migration: Adding leading zeros to 'motor.number'")
    env = util.env(cr)
    motors = env["motor"].search([])

    for motor in motors:
        motor.motor_number = f"M-{str(motor.id).zfill(6)}"

    _logger.info("Post-migration: Added leading zeros to 'motor.number'")
