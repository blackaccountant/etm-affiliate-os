"""
Default AI Workforce

Registers the standard AI workers
available to ETM Affiliate OS.
"""

from app.workforce.worker_info import WorkerInfo


def create_default_workers():

    return [

        # ==================================================
        # Product Hunter
        # ==================================================

        WorkerInfo(
            name="Product Hunter",
            worker_type="AI Agent",
            capabilities=[
                "product_discovery",
                "affiliate_research",
                "market_analysis",
            ],
            status="ONLINE",
        ),

        # ==================================================
        # Research Agent
        # ==================================================

        WorkerInfo(
            name="Research Agent",
            worker_type="AI Agent",
            capabilities=[
                "web_research",
                "competitor_analysis",
                "data_collection",
            ],
            status="ONLINE",
        ),

        # ==================================================
        # Content Writer
        # ==================================================

        WorkerInfo(
            name="Content Writer",
            worker_type="AI Agent",
            capabilities=[
                "content_generation",
                "seo_content",
                "product_reviews",
            ],
            status="ONLINE",
        ),

    ]