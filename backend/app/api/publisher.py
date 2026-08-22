"""
Publisher API

Handles publishing queue management
and publishing execution.
"""


from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)

from sqlalchemy.orm import Session


from app.database.session import SessionLocal

from app.models.publishing_queue import (
    PublishingQueue,
)

from app.models.affiliate_content_asset import (
    AffiliateContentAsset,
)

from app.services.publisher_service import (
    PublisherService,
)



router = APIRouter(
    prefix="/publisher",
    tags=["Publisher"]
)



def get_db():

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()



# ==================================================
# GET PUBLISHING QUEUE
# ==================================================

@router.get("/queue")
def get_publishing_queue(
    db: Session = Depends(get_db),
):

    rows = (
        db.query(
            PublishingQueue
        )
        .order_by(
            PublishingQueue.id.desc()
        )
        .all()
    )


    results = []


    for item in rows:

        asset = (
            db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.id
                ==
                item.content_asset_id
            )
            .first()
        )


        results.append(
            {

                "queue_id": item.id,

                "content_asset_id":
                    item.content_asset_id,

                "title":
                    asset.title
                    if asset
                    else None,

                "status":
                    item.status,

                "channel":
                    item.channel,

                "published_url":
                    item.published_url,

                "created_at":
                    item.created_at,

            }
        )


    return {

        "success": True,

        "count": len(results),

        "queue": results

    }



# ==================================================
# PUBLISH CONTENT
# ==================================================

@router.post("/publish/{queue_id}")
def publish_content(
    queue_id: int,

    db: Session = Depends(get_db),

):


    queue_item = (
        db.query(
            PublishingQueue
        )
        .filter(
            PublishingQueue.id
            ==
            queue_id
        )
        .first()
    )


    if not queue_item:

        raise HTTPException(
            status_code=404,
            detail="Publishing queue item not found"
        )



    try:

        service = PublisherService(
            db
        )


        result = service.publish(
            queue_id
        )


        return {

            "success": True,

            "queue_id":
                result.id,

            "status":
                result.status,

            "published_url":
                result.published_url

        }


    except Exception as e:


        raise HTTPException(
            status_code=500,
            detail=str(e)
        )