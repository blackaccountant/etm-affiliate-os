import json
from app.content_intelligence.generation_contracts import ContentGenerationPrompt

OUTPUT_SCHEMA = {"type":"object", "required":["title","hook","body","cta","disclosure","claims"], "properties":{"title":{"type":"string"},"hook":{"type":"string"},"body":{"type":"string"},"cta":{"type":"string"},"disclosure":{"type":"string"},"claims":{"type":"array","items":{"type":"object","required":["text","source_evidence_ids"],"properties":{"text":{"type":"string"},"source_evidence_ids":{"type":"array","items":{"type":"string"}}}}}}}

class GroundedContentPromptBuilder:
    def build(self, brief, links):
        ledger = [{"evidence_observation_id": link.evidence_observation_id, "usage_role": link.usage_role, "claim_type": link.evidence_observation.claim_type, "observed_value": link.evidence_observation.observed_value, "source_url": link.evidence_observation.source_url, "excerpt": link.evidence_observation.excerpt, "confidence": link.evidence_observation.confidence} for link in links]
        strategy = {key:getattr(brief, key) for key in ("content_type","channel_intent","objective","audience_intent","audience_problem","angle","call_to_action","tone","required_disclosure","key_benefits","target_keywords","constraints")}
        text = "You create grounded structured content. Use only the evidence ledger. Never invent commission, cookie duration, pricing, discounts, features, capabilities, guarantees, testimonials, urgency, scarcity, income, or comparisons. Every factual claim must cite ledger evidence IDs. Return JSON matching the output schema.\nSTRATEGY=" + json.dumps(strategy, sort_keys=True, default=str) + "\nEVIDENCE_LEDGER=" + json.dumps(ledger, sort_keys=True, default=str) + "\nOUTPUT_SCHEMA=" + json.dumps(OUTPUT_SCHEMA, sort_keys=True)
        return ContentGenerationPrompt(text=text, evidence_ids=tuple(item["evidence_observation_id"] for item in ledger))
