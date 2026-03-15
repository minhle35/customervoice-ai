from celery import Celery

celery_app = Celery(
    "customer_voice_ai",
    broker="${CELERY_BROKER_URL}",
    backend="${CELERY_RESULT_BACKEND}",
)

