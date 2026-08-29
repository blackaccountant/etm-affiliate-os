"""Build one provider-neutral prompt for a grounded content transformation."""

import json

from app.content_intelligence.generation_contracts import ContentGenerationPrompt
from app.content_intelligence.prompt_builder import OUTPUT_SCHEMA


class GroundedRepurposingPromptBuilder:
    def build(self, source_artifact, whitelist, request) -> ContentGenerationPrompt:
        source = {
            "content_type": source_artifact.content_type,
            "title": source_artifact.title,
            "hook": source_artifact.hook,
            "body": source_artifact.body,
            "cta": source_artifact.call_to_action,
            "disclosure": source_artifact.affiliate_disclosure,
            "claims": source_artifact.claims,
        }
        target = {
            "target_content_type": request.target_content_type,
            "channel_intent": request.channel_intent,
            "tone_constraints": request.tone_constraints,
            "format_constraints": request.format_constraints,
        }
        text = (
            "Transform the approved source artifact into the requested format. "
            "Do not add facts or evidence IDs, alter factual values, remove the affiliate disclosure, "
            "or introduce guarantees, discounts, scarcity, or urgency. Preserve the safe CTA. "
            "Every factual claim must cite one or more approved evidence IDs. Return JSON matching the output schema.\n"
            "SOURCE_ARTIFACT=" + json.dumps(source, sort_keys=True, default=str) + "\n"
            "APPROVED_EVIDENCE_WHITELIST=" + json.dumps(sorted(whitelist)) + "\n"
            "TARGET=" + json.dumps(target, sort_keys=True, default=str) + "\n"
            "OUTPUT_SCHEMA=" + json.dumps(OUTPUT_SCHEMA, sort_keys=True)
        )
        return ContentGenerationPrompt(text=text, evidence_ids=tuple(sorted(whitelist)))
