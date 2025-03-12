import logging

from odoo.sql_db import Cursor

_logger = logging.getLogger(__name__)


# noinspection SqlResolve
def migrate(cr: Cursor, version: str) -> None:
    _logger.info("Pre-migration: Storing existing stroke and configuration data")
    cr.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS temp_motor_data (
            motor_id INT,
            old_stroke VARCHAR,
            old_config VARCHAR
        )
    """
    )

    cr.execute(
        """
        INSERT INTO temp_motor_data (motor_id, old_stroke, old_config)
        SELECT id, motor_stroke, motor_configuration FROM motor
    """
    )
