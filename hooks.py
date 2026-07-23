import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Disable binotel_connect phone buttons on partner form to avoid duplicates."""
    view = env.ref('binotel_connect.view_partner_form_inherit', raise_if_not_found=False)
    if view and view.active:
        view.active = False
        _logger.info('zadarma_odoo: Deactivated binotel_connect partner phone buttons view')
