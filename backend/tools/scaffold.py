import re


def snake_case(name: str) -> str:
    """
    Convert CamelCase or PascalCase to snake_case.

    Examples:
        ProductHunter -> product_hunter
        SEOHunter -> seo_hunter
        AIWriter -> ai_writer
        OpenAIWorker -> openai_worker
    """

    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)

    return name.lower()