from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


@dataclass
class Notification:
    kind: str
    user_id: int
    title: str
    message: str


class NotificationSink:
    def send(self, notification: Notification) -> None:
        raise NotImplementedError


class LocalNotificationSink(NotificationSink):
    def __init__(self, repository) -> None:
        self.repository = repository

    def send(self, notification: Notification) -> None:
        self.repository.create_notification_event(
            notification.kind,
            notification.user_id,
            notification.title,
            notification.message,
            "queued",
        )


class SlackWebhookSink(NotificationSink):
    def __init__(self, repository, webhook_url: Optional[str]) -> None:
        self.repository = repository
        self.webhook_url = webhook_url

    def send(self, notification: Notification) -> None:
        self.repository.create_notification_event(
            notification.kind,
            notification.user_id,
            notification.title,
            notification.message,
            "queued",
        )
        if not self.webhook_url:
            return
        payload = json.dumps({"text": f"*{notification.title}*\n{notification.message}"}).encode("utf-8")
        request = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=3):
                self.repository.mark_latest_notification_delivered(notification.user_id, notification.kind)
        except urllib.error.URLError:
            pass
