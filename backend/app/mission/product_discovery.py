"""
Product Discovery Mission

Finds and ranks affiliate opportunities.
"""

from app.mission.mission import Mission


class ProductDiscoveryMission(Mission):

    def __init__(
        self,
        url: str | None = None,
    ):

        metadata = {}

        if url:

            metadata["url"] = url


        super().__init__(
            name="ProductDiscovery",

            objective=(
                "Discover profitable affiliate "
                "product opportunities"
            ),

            workflow="product_discovery",

            metadata=metadata,

            required_capability=(
                "product_discovery"
            ),
        )