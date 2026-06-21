"""
P9A PDF generation (native layout matching KRA P9A — no external template file required).
"""
from app.services.p9_pdf_builder import build_p9a_context, build_p9a_pdf

# Backward-compatible aliases used by reports route
build_p9a_overlay_context = build_p9a_context
fill_p9a_template_pdf = build_p9a_pdf

__all__ = [
    'build_p9a_context',
    'build_p9a_pdf',
    'build_p9a_overlay_context',
    'fill_p9a_template_pdf',
]
