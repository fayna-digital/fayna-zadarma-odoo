try:
    from . import controllers, models
    from .hooks import post_init_hook
except ImportError:  # pragma: no cover
    # This module is only ever meant to be imported as `odoo.addons.zadarma_odoo`
    # from inside a running Odoo instance. `pytest` (used for the
    # framework-independent unit tests under tests/) resolves this file's
    # package root before collecting tests/ or lib/ and may import it
    # directly with no parent package — safe to no-op in that case.
    pass
