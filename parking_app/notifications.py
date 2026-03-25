from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional


@dataclass
class Notification:
    kind: str
    user_id: int
    title: str
    message: str
    recipient_email: Optional[str] = None


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


class MultiChannelNotificationSink(NotificationSink):
    def __init__(
        self,
        repository,
        webhook_url: Optional[str],
        *,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        smtp_use_tls: bool = True,
        sender_email: Optional[str] = None,
        guide_url: Optional[str] = None,
    ) -> None:
        self.repository = repository
        self.webhook_url = webhook_url
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port or 587
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.smtp_use_tls = smtp_use_tls
        self.sender_email = sender_email or smtp_username or "parking-tool@local.test"
        self.guide_url = guide_url or os.environ.get("PARKING_GUIDE_URL", "").strip()

    def send(self, notification: Notification) -> None:
        self.repository.create_notification_event(
            notification.kind,
            notification.user_id,
            notification.title,
            notification.message,
            "queued",
        )
        delivered = False
        if self._send_slack(notification):
            delivered = True
        if self._send_email(notification):
            delivered = True
        if delivered:
            self.repository.mark_latest_notification_delivered(notification.user_id, notification.kind)

    def _send_slack(self, notification: Notification) -> bool:
        if not self.webhook_url:
            return False
        payload = json.dumps({"text": f"*{notification.title}*\n{notification.message}"}).encode("utf-8")
        request = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=3):
                return True
        except urllib.error.URLError:
            return False

    def _send_email(self, notification: Notification) -> bool:
        recipient = (notification.recipient_email or self._lookup_user_email(notification.user_id) or "").strip()
        if not recipient or not self.smtp_host:
            return False

        message = EmailMessage()
        message["Subject"] = notification.title
        message["From"] = self.sender_email
        message["To"] = recipient
        message.set_content(self._email_body(notification))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=5) as server:
                if self.smtp_use_tls:
                    server.starttls()
                if self.smtp_username and self.smtp_password:
                    server.login(self.smtp_username, self.smtp_password)
                server.send_message(message)
            return True
        except OSError:
            return False

    def _lookup_user_email(self, user_id: int) -> Optional[str]:
        user = self.repository.get_user(user_id)
        return user["email"] if user else None

    def _email_body(self, notification: Notification) -> str:
        if notification.kind == "guest_booking_created" and self.guide_url:
            return f"{notification.message}\n\nGuide video: {self.guide_url}"
        return notification.message
