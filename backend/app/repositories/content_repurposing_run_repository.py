"""Focused persistence operations for repurposing lineage."""

from sqlalchemy.orm import Session

from app.models.content_repurposing_run import ContentRepurposingRun


class ContentRepurposingRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **values) -> ContentRepurposingRun:
        row = ContentRepurposingRun(**values)
        self.db.add(row)
        self.db.flush()
        return row

    def get_by_id(self, run_id: str) -> ContentRepurposingRun | None:
        return self.db.get(ContentRepurposingRun, run_id)

    def get_by_generation_run_id(self, generation_run_id: str) -> ContentRepurposingRun | None:
        return self.db.query(ContentRepurposingRun).filter_by(generation_run_id=generation_run_id).first()

    def get_by_result_artifact_id(self, artifact_id: str) -> ContentRepurposingRun | None:
        return self.db.query(ContentRepurposingRun).filter_by(result_artifact_id=artifact_id).first()

    def set_result(self, row: ContentRepurposingRun, artifact_id: str) -> ContentRepurposingRun:
        row.result_artifact_id = artifact_id
        return row
