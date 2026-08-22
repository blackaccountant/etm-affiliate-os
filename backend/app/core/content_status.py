"""
Affiliate Content Lifecycle States
"""


class ContentStatus:

    PLANNED = "planned"

    GENERATED = "generated"

    SEO_REVIEW = "seo_review"

    APPROVED = "approved"

    PUBLISHED = "published"

    TRACKING = "tracking"


    ALL = [
        PLANNED,
        GENERATED,
        SEO_REVIEW,
        APPROVED,
        PUBLISHED,
        TRACKING,
    ]