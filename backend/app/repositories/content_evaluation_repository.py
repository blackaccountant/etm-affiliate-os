from app.models.content_evaluation import ContentEvaluation
class ContentEvaluationRepository:
    def __init__(self, db): self.db = db
    def create(self, **values):
        row = ContentEvaluation(**values); self.db.add(row); self.db.flush(); return row
    def get_by_id(self, value): return self.db.get(ContentEvaluation, value)
    def get_by_artifact_id(self, value): return self.db.query(ContentEvaluation).filter_by(artifact_id=value).order_by(ContentEvaluation.created_at.asc()).all()
    def get_by_identity(self, artifact_id, evaluator_version, policy_version): return self.db.query(ContentEvaluation).filter_by(artifact_id=artifact_id, evaluator_version=evaluator_version, policy_version=policy_version).first()
