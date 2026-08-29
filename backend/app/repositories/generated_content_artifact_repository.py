from sqlalchemy.orm import Session

from app.models.generated_content_artifact import GeneratedContentArtifact


class GeneratedContentArtifactRepository:
    def __init__(self, db: Session): self.db = db
    def create(self, **values):
        artifact = GeneratedContentArtifact(**values)
        self.db.add(artifact)
        self.db.flush()
        return artifact
    def get_by_id(self, artifact_id: str): return self.db.get(GeneratedContentArtifact, artifact_id)
    def get_by_generation_run_id(self, run_id: str):
        return self.db.query(GeneratedContentArtifact).filter_by(generation_run_id=run_id).first()
    def list_by_content_brief_id(self, brief_id: str):
        return self.db.query(GeneratedContentArtifact).filter_by(content_brief_id=brief_id).order_by(GeneratedContentArtifact.created_at.asc()).all()
