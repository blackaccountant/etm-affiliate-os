"""
ETM Affiliate OS
Content Writer Agent

Generates publish-ready affiliate content from an
AffiliateContentAsset.

This service is intentionally deterministic and safe:
- No nested f-strings
- No external API dependency
- Handles missing/None asset fields
- Produces content, SEO title and SEO description
- Compatible with ContentExecutionService
"""

from typing import Any, Dict

from app.models.affiliate_content_asset import AffiliateContentAsset


class ContentWriterAgent:
    """
    Generates the final written content for an affiliate
    content asset.
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_text(value: Any, default: str = "") -> str:
        """
        Convert a value safely to text.
        """
        if value is None:
            return default

        if isinstance(value, str):
            return value.strip()

        return str(value).strip()

    @staticmethod
    def _list_to_text(value: Any) -> str:
        """
        Convert a list/tuple/set or scalar into readable text.
        """
        if value is None:
            return ""

        if isinstance(value, (list, tuple, set)):
            items = []

            for item in value:
                text = str(item).strip()

                if text:
                    items.append(text)

            return ", ".join(items)

        return str(value).strip()

    @staticmethod
    def _build_default_summary(
        product_name: str,
        category: str,
    ) -> str:
        """
        Build a fallback introduction when no summary
        is available.
        """

        if not product_name:
            product_name = "This solution"

        if not category:
            category = "business software"

        return (
            f"{product_name} is a solution in the "
            f"{category} category. "
            "This guide explains what it offers, who it is "
            "best suited for, and how businesses can evaluate "
            "whether it is a good fit."
        )

    @staticmethod
    def _build_audience_section(
        audience: Any,
    ) -> str:
        """
        Convert audience information into readable Markdown.
        """

        if audience is None:
            return (
                "- Business owners\n"
                "- Startup founders\n"
                "- Marketing teams\n"
                "- Sales professionals\n"
                "- Software buyers"
            )

        if isinstance(audience, (list, tuple, set)):
            lines = []

            for item in audience:
                text = str(item).strip()

                if text:
                    lines.append(f"- {text}")

            if lines:
                return "\n".join(lines)

        text = str(audience).strip()

        if text:
            return text

        return (
            "- Business owners\n"
            "- Startup founders\n"
            "- Marketing teams\n"
            "- Sales professionals\n"
            "- Software buyers"
        )

    @staticmethod
    def _build_outline(
        content_outline: Any,
    ) -> list[str]:
        """
        Convert the supplied content outline into a list
        of section names.
        """

        if content_outline is None:
            return [
                "Introduction",
                "Overview",
                "Key Features",
                "Benefits",
                "Who Should Use It?",
                "Pros and Cons",
                "Conclusion",
            ]

        if isinstance(content_outline, (list, tuple, set)):
            result = []

            for item in content_outline:
                text = str(item).strip()

                if text:
                    result.append(text)

            if result:
                return result

        text = str(content_outline).strip()

        if text:
            return [text]

        return [
            "Introduction",
            "Overview",
            "Key Features",
            "Benefits",
            "Who Should Use It?",
            "Pros and Cons",
            "Conclusion",
        ]

    # ------------------------------------------------------------------
    # Main generation method
    # ------------------------------------------------------------------

    def generate(
        self,
        asset: AffiliateContentAsset,
    ) -> Dict[str, str]:
        """
        Generate publish-ready content.

        Returns:

        {
            "content": "...",
            "seo_title": "...",
            "seo_description": "..."
        }
        """

        if asset is None:
            raise ValueError(
                "AffiliateContentAsset is required."
            )

        # --------------------------------------------------------------
        # Extract asset data
        # --------------------------------------------------------------

        title = self._safe_text(
            getattr(asset, "title", None),
            "Affiliate Product Guide",
        )

        target_keyword = self._safe_text(
            getattr(asset, "target_keyword", None),
            title,
        )

        audience = getattr(
            asset,
            "audience",
            None,
        )

        search_intent = self._safe_text(
            getattr(asset, "search_intent", None),
            "Informational",
        )

        content_outline = getattr(
            asset,
            "content_outline",
            None,
        )

        call_to_action = self._safe_text(
            getattr(asset, "call_to_action", None),
            "Learn more and evaluate the solution",
        )

        # These fields may not exist on every version of the model.
        # getattr keeps the service compatible with older schemas.
        product_name = self._safe_text(
            getattr(asset, "product_name", None),
            "",
        )

        category = self._safe_text(
            getattr(asset, "category", None),
            "",
        )

        summary = self._safe_text(
            getattr(asset, "summary", None),
            "",
        )

        # --------------------------------------------------------------
        # Resolve product name
        # --------------------------------------------------------------

        if not product_name:
            product_name = title

        # --------------------------------------------------------------
        # Resolve summary
        # --------------------------------------------------------------

        if not summary:
            summary = self._build_default_summary(
                product_name,
                category,
            )

        # --------------------------------------------------------------
        # Resolve audience
        # --------------------------------------------------------------

        audience_text = self._build_audience_section(
            audience
        )

        # --------------------------------------------------------------
        # Resolve outline
        # --------------------------------------------------------------

        outline = self._build_outline(
            content_outline
        )

        # --------------------------------------------------------------
        # Build content
        # --------------------------------------------------------------

        sections: list[str] = []

        sections.append(
            f"# {title}"
        )

        sections.append(
            "## Introduction\n\n"
            f"{summary}\n\n"
            f"This guide focuses on the keyword "
            f"**{target_keyword}** and is designed for "
            f"readers with {search_intent.lower()} search intent."
        )

        sections.append(
            "## Overview\n\n"
            f"{product_name} is positioned within the "
            f"{category or 'business software'} market. "
            "Before choosing any product or service, users "
            "should consider features, pricing, usability, "
            "support, integrations, and how well the solution "
            "matches their specific requirements."
        )

        # --------------------------------------------------------------
        # Outline-driven sections
        # --------------------------------------------------------------

        generated_outline_sections = set()

        for section_name in outline:
            normalized = section_name.strip()

            if not normalized:
                continue

            normalized_lower = normalized.lower()

            # Avoid duplicating sections we already generate.
            if normalized_lower in {
                "introduction",
                "overview",
                "conclusion",
            }:
                continue

            if normalized_lower in generated_outline_sections:
                continue

            generated_outline_sections.add(
                normalized_lower
            )

            if normalized_lower in {
                "key features",
                "features",
                "product features",
            }:
                section_body = (
                    f"{product_name} should be evaluated based "
                    "on the features that matter most to the "
                    "intended user. Important areas may include "
                    "core functionality, integrations, automation, "
                    "reporting, usability, scalability, and support."
                )

            elif normalized_lower in {
                "benefits",
                "key benefits",
            }:
                section_body = (
                    "Potential benefits include improved workflows, "
                    "better productivity, easier access to useful "
                    "business capabilities, reduced manual work, "
                    "and the ability to scale operations as needs grow."
                )

            elif normalized_lower in {
                "pricing",
                "pricing comparison",
            }:
                section_body = (
                    f"Pricing for {product_name} should be checked "
                    "directly with the provider because plans, "
                    "features, promotions, usage limits, and "
                    "regional availability can change over time."
                )

            elif normalized_lower in {
                "pros and cons",
                "advantages and disadvantages",
            }:
                section_body = (
                    "**Potential advantages**\n\n"
                    "- Broad functionality\n"
                    "- Potential productivity improvements\n"
                    "- Scalable workflows\n"
                    "- Integration opportunities\n\n"
                    "**Potential limitations**\n\n"
                    "- Pricing may vary by plan\n"
                    "- Some advanced features may require paid tiers\n"
                    "- Users should compare alternatives before committing"
                )

            elif normalized_lower in {
                "who should use it?",
                "who should use it",
                "target audience",
            }:
                section_body = (
                    "The product may be relevant to the following "
                    "audiences:\n\n"
                    f"{audience_text}"
                )

            elif normalized_lower in {
                "alternatives",
                "alternatives and competitors",
                "competitors",
            }:
                section_body = (
                    "Users should compare competing solutions "
                    "before making a final decision. The best "
                    "alternative depends on price, features, "
                    "integrations, support, ease of use, and "
                    "specific business requirements."
                )

            elif normalized_lower in {
                "market comparison",
                "feature comparison",
                "pricing comparison",
                "best choice",
            }:
                section_body = (
                    "A useful comparison should consider the "
                    "features that matter to the target audience, "
                    "total cost, ease of implementation, available "
                    "integrations, customer support, and expected "
                    "return on investment."
                )

            else:
                section_body = (
                    f"This section examines {normalized} in the "
                    f"context of {product_name}. Readers should "
                    "focus on practical use cases, measurable "
                    "benefits, limitations, and fit for their "
                    "specific requirements."
                )

            sections.append(
                f"## {normalized}\n\n"
                f"{section_body}"
            )

        # --------------------------------------------------------------
        # Audience section
        # --------------------------------------------------------------

        sections.append(
            "## Who Should Use It?\n\n"
            "This solution may be relevant to:\n\n"
            f"{audience_text}"
        )

        # --------------------------------------------------------------
        # Conclusion
        # --------------------------------------------------------------

        sections.append(
            "## Conclusion\n\n"
            f"{product_name} may be worth considering for users "
            "whose requirements align with its capabilities. "
            "Before making a purchasing decision, compare the "
            "available plans, features, alternatives, support, "
            "and expected business value."
        )

        # --------------------------------------------------------------
        # Call to action
        # --------------------------------------------------------------

        sections.append(
            "## Next Step\n\n"
            f"{call_to_action}"
        )

        content = "\n\n".join(
            sections
        )

        # --------------------------------------------------------------
        # SEO metadata
        # --------------------------------------------------------------

        seo_title = (
            f"{title} | Complete Guide"
        )

        seo_description = (
            f"Learn about {title}. "
            f"Explore features, benefits, pricing, alternatives, "
            f"target users, and practical recommendations."
        )

        # Keep SEO description within a sensible search-snippet range.
        if len(seo_description) > 160:
            seo_description = (
                seo_description[:157].rstrip()
                + "..."
            )

        return {
            "content": content,
            "seo_title": seo_title,
            "seo_description": seo_description,
        }