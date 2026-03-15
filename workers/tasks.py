from .celery_app import celery_app


@celery_app.task
def run_ingestion():
    return "ok"

