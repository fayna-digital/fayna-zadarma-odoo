import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Deactivate binotel_connect phone buttons on partner form to avoid duplicates."""
    cr.execute("""
        UPDATE ir_ui_view SET active = false
        WHERE id = (
            SELECT res_id FROM ir_model_data
            WHERE module = 'binotel_connect'
              AND name = 'view_partner_form_inherit'
              AND model = 'ir.ui.view'
        )
        AND active = true
    """)
    if cr.rowcount:
        _logger.info("zadarma_odoo migration: Deactivated binotel_connect partner phone buttons view")
