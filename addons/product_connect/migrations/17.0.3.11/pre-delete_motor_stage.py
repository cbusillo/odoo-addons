import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


# noinspection SqlResolve
def migrate(cr: Cursor, version: str) -> None:
    _logger.info("Pre-migration: Delete motor stage")

    util.remove_field(cr, "motor", "stage")

    _logger.info("Pre-migration: Deleted motor stage")
