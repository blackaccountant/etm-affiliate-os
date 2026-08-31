"""
Default AI Workforce

Registers the standard AI workers
available to ETM Affiliate OS.
"""

from app.workforce.worker_info import WorkerInfo
from app.workforce.status import WorkerStatus


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
            status=WorkerStatus.ONLINE,
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
                "audience_signal_extraction",
            ],
            status=WorkerStatus.ONLINE,
        ),

        # ==================================================
        # Content Writer
        # ==================================================

        WorkerInfo(
            name="Content Writer",
            worker_type="AI Agent",
            capabilities=[
                "content_generation",
                "content_distribution",
                "outreach_delivery",
                "seo_content",
                "product_reviews",
            ],
            status=WorkerStatus.ONLINE,
        ),

        # Cold-delivery orchestration is deliberately isolated from the general
        # content-writing authority.  It still cannot resolve or send recipients.
        WorkerInfo(
            name="Cold Delivery Orchestrator",
            worker_type="AI Agent",
            capabilities=["cold_b2b_delivery"],
            status=WorkerStatus.ONLINE,
        ),

    ]
