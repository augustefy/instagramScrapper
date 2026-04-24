"""
Point d'entrée du worker RQ.

Sur macOS, RQ's Worker standard utilise os.fork() ce qui crashe à cause
des APIs Objective-C non fork-safe (_scproxy / proxy detection).
SimpleWorker exécute les jobs dans le même process (pas de fork) — parfait
pour le développement local. Sur Linux (Docker/prod), on utilise Worker
classique avec fork pour l'isolation complète.
"""

import platform
import sys

import redis
from rq import Queue, SimpleWorker, Worker

from api.config import get_settings

settings = get_settings()

QUEUES = ["scrapes"]


def main() -> None:
    conn = redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=conn) for name in QUEUES]

    if platform.system() == "Darwin":
        print("[worker] macOS détecté → SimpleWorker (sans fork)", flush=True)
        WorkerClass = SimpleWorker
    else:
        print("[worker] Linux détecté → Worker standard (avec fork)", flush=True)
        WorkerClass = Worker

    worker = WorkerClass(queues, connection=conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
