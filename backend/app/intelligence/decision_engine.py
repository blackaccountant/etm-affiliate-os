"""
Affiliate Decision Engine

Transforms intelligence scores into
business actions.
"""

from app.intelligence.models import IntelligenceResult


class AffiliateDecisionEngine:


    def decide(
        self,
        intelligence: IntelligenceResult,
    ):

        score = intelligence.score


        if score >= 80:

            return {

                "decision": "PURSUE",

                "priority": "HIGH",

                "score": score,

                "grade": intelligence.grade,

                "confidence": intelligence.confidence,

                "actions": [

                    "Find affiliate partnership",

                    "Create SEO content strategy",

                    "Build conversion funnel",

                ],

            }


        elif score >= 60:

            return {

                "decision": "MONITOR",

                "priority": "MEDIUM",

                "score": score,

                "grade": intelligence.grade,

                "confidence": intelligence.confidence,

                "actions": [

                    "Research affiliate availability",

                    "Collect more market signals",

                    "Monitor competitors",

                ],

            }


        else:

            return {

                "decision": "REJECT",

                "priority": "LOW",

                "score": score,

                "grade": intelligence.grade,

                "confidence": intelligence.confidence,

                "actions": [

                    "Archive opportunity",

                    "Review weaknesses",

                ],

            }