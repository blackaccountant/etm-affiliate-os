"""
Generated ETM Mission
"""


from app.mission.mission import Mission


class AffiliateDiscoveryMission(Mission):


    def __init__(self):

        super().__init__(
            name="AffiliateDiscovery",
            objective="Define mission objective",
            workflow="default_workflow",
        )