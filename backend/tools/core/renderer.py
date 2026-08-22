"""
Template rendering.
"""

from core.templates import TEMPLATE_DIR


def render(
    template_name: str,
    **context,
):

    template = (
        TEMPLATE_DIR /
        template_name
    )

    text = template.read_text(
        encoding="utf-8"
    )

    return text.format(
        **context
    )