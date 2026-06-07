from celery import Celery

celery_app = Celery("outreach_worker")

celery_app.config_from_object({
    "broker_url": "redis://localhost:6379/0",
    "result_backend": "redis://localhost:6379/1",
    "task_serializer": "json",
    "result_serializer": "json",
    "accept_content": ["json"],
    "task_acks_late": True,
    "task_reject_on_worker_lost": True,
    "task_track_started": True,
    "worker_prefetch_multiplier": 1,
    "result_expires": 3600,
    "task_queues": {
        "outreach:high":    {"exchange": "outreach", "routing_key": "high"},
        "outreach:default": {"exchange": "outreach", "routing_key": "default"},
        "outreach:low":     {"exchange": "outreach", "routing_key": "low"},
    },
    "task_default_queue": "outreach:default",
    "task_default_exchange": "outreach",
    "task_default_routing_key": "default",
})

celery_app.autodiscover_tasks(["tasks"])
