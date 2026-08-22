"""
ETM Affiliate OS
End-to-End Affiliate Pipeline Test
"""

import sys
import os


sys.path.append(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)


from app.workflows.affiliate.affiliate_discovery_workflow import (
    AffiliateDiscoveryWorkflow,
)


from app.database.session import (
    SessionLocal,
)


from app.models.product import (
    Product,
)


from app.models.affiliate_program import (
    AffiliateProgram,
)


from app.models.affiliate_opportunity import (
    AffiliateOpportunity,
)



def run_test():


    print("=" * 60)
    print("ETM AFFILIATE OS PIPELINE TEST")
    print("=" * 60)



    workflow = (
        AffiliateDiscoveryWorkflow()
    )


    result = workflow.execute(
        {
            "url": "https://hubspot.com"
        }
    )



    print("\nWORKFLOW STATUS:")
    print(result.success)



    print("\nEVENTS:")
    for event in result.events:
        print("-", event)



    if not result.success:

        print("\nERRORS:")
        print(result.errors)

        return



    db = SessionLocal()



    print("\nDATABASE CHECK")
    print("-" * 60)



    products = (
        db.query(Product)
        .all()
    )


    programs = (
        db.query(AffiliateProgram)
        .all()
    )


    opportunities = (
        db.query(AffiliateOpportunity)
        .all()
    )



    print(
        "Products:",
        len(products)
    )


    print(
        "Affiliate Programs:",
        len(programs)
    )


    print(
        "Opportunities:",
        len(opportunities)
    )



    if opportunities:

        opportunity = opportunities[-1]


        print("\nLATEST OPPORTUNITY")

        print(
            "Product ID:",
            opportunity.product_id
        )

        print(
            "Grade:",
            opportunity.opportunity_grade
        )

        print(
            "Confidence:",
            opportunity.confidence
        )



    db.close()



    print("\nTEST COMPLETE")



if __name__ == "__main__":

    run_test()