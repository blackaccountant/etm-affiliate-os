"""
Generated Mission Test
"""


from app.mission.affiliate_discovery import AffiliateDiscoveryMission



def test_mission_creation():

    mission = AffiliateDiscoveryMission()


    assert (
        mission.name
        ==
        "AffiliateDiscovery"
    )