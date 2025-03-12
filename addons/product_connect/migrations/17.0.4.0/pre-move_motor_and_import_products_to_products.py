import logging

from odoo.sql_db import Cursor
from odoo.upgrade import util

_logger = logging.getLogger(__name__)


def cleanup_invalid_references(cr: Cursor):
    _logger.info("Cleaning up invalid references")

    cr.execute(
        """
        SELECT DISTINCT mpr.product_id, count(*) as count
        FROM motor_product_with_reference_product_rel mpr
        WHERE NOT EXISTS (
            SELECT 1 FROM product_template pt 
            WHERE pt.id = mpr.product_id
        )
        GROUP BY mpr.product_id
    """
    )

    invalid_refs = cr.fetchall()
    if invalid_refs:
        _logger.warning(f"Found {len(invalid_refs)} invalid product references to clean up")
        for product_id, count in invalid_refs:
            _logger.info(f"Removing {count} invalid references for product_id: {product_id}")

        cr.execute(
            """
            DELETE FROM motor_product_with_reference_product_rel
            WHERE NOT EXISTS (
                SELECT 1 FROM product_template pt 
                WHERE pt.id = motor_product_with_reference_product_rel.product_id
            )
        """
        )
    else:
        _logger.info("No invalid references found")


def migrate(cr: Cursor, version: str):
    """Pre-migration: Clean up constraints and prepare for model changes"""
    if not version:
        return

    _logger.info("Starting pre-migration cleanup")

    cr.execute(
        """
        DO $$ 
        BEGIN
            -- Drop foreign key constraints on the relation table
            EXECUTE (
                SELECT string_agg('ALTER TABLE ' || table_name || 
                                ' DROP CONSTRAINT ' || constraint_name || ';', ' ')
                FROM information_schema.table_constraints 
                WHERE table_name = 'motor_product_with_reference_product_rel'
                AND constraint_type = 'FOREIGN KEY'
            );
        END $$;
    """
    )

    cleanup_invalid_references(cr)

    for table in ["motor_product", "product_import", "product_template"]:
        if util.table_exists(cr, table):
            # noinspection SqlResolve
            cr.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {table}_default_code_idx 
                ON {table} (default_code)
            """
            )

    _logger.info("Pre-migration cleanup completed")
