import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from parking_app import server as server_module
from parking_app.notifications import LocalNotificationSink
from parking_app.repository import Repository
from parking_app.services import BannerError, BannerService, BookingService, UploadedBannerImage


def make_image_bytes(width: int = 1600, height: int = 1000, fmt: str = "PNG") -> bytes:
    image = Image.new("RGB", (width, height), "#2b87ff")
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def multipart_body(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----CodexBannerBoundary"
    lines: list[bytes] = []
    for key, value in fields.items():
        lines.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    for key, (filename, body, content_type) in files.items():
        lines.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                body,
                b"\r\n",
            ]
        )
    lines.append(f"--{boundary}--\r\n".encode())
    return b"".join(lines), boundary


class BannerRepositoryAndServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.temp_dir.name) / "test.db", seed_demo_data=False)
        self.service = BannerService(
            self.repo,
            Path(self.temp_dir.name) / "uploads",
            Path(self.temp_dir.name) / "artifacts",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_repository_seeds_banner_templates(self) -> None:
        templates = self.repo.list_banner_template_sets()
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]["id"], "leasingmarkt-core-campaign")

    def test_generate_banner_run_creates_zip_and_history(self) -> None:
        run_id = self.service.generate_banner_run(
            user_id=2,
            template_set_id="leasingmarkt-core-campaign",
            headline="Your next car, simplified",
            subline="Create export-ready banners without leaving the internal tool.",
            button_text="See offers",
            image=UploadedBannerImage("hero.png", "image/png", make_image_bytes()),
        )
        run = self.service.get_run_for_user(2, run_id)
        self.assertIsNotNone(run)
        self.assertEqual(run["status"], "completed")
        zip_path = Path(self.temp_dir.name) / "artifacts" / run["export_artifact_path"]
        self.assertTrue(zip_path.exists())
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            self.assertIn("manifest.json", names)
            self.assertIn("plugin-payload.json", names)
            self.assertTrue(any(name.endswith(".png") for name in names))
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            self.assertEqual(manifest["fields"]["headline"], "Your next car, simplified")

    def test_validation_failure_creates_failed_history_entry(self) -> None:
        with self.assertRaises(BannerError):
            self.service.generate_banner_run(
                user_id=2,
                template_set_id="leasingmarkt-core-campaign",
                headline="X" * 60,
                subline="Valid subline",
                button_text="Button",
                image=UploadedBannerImage("hero.png", "image/png", make_image_bytes()),
            )
        runs = self.service.list_runs_for_user(2)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "failed")

    def test_small_image_is_rejected(self) -> None:
        with self.assertRaises(BannerError):
            self.service.generate_banner_run(
                user_id=2,
                template_set_id="leasingmarkt-core-campaign",
                headline="Valid headline",
                subline="Valid subline",
                button_text="Button",
                image=UploadedBannerImage("tiny.png", "image/png", make_image_bytes(400, 300)),
            )


class BannerServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_repo = server_module.REPO
        self.original_service = server_module.SERVICE
        self.original_banner_service = server_module.BANNER_SERVICE

        repo = Repository(Path(self.temp_dir.name) / "server.db")
        server_module.REPO = repo
        server_module.SERVICE = BookingService(repo, LocalNotificationSink(repo))
        server_module.BANNER_SERVICE = BannerService(
            repo,
            Path(self.temp_dir.name) / "uploads",
            Path(self.temp_dir.name) / "artifacts",
        )

    def tearDown(self) -> None:
        server_module.REPO = self.original_repo
        server_module.SERVICE = self.original_service
        server_module.BANNER_SERVICE = self.original_banner_service
        self.temp_dir.cleanup()

    def make_handler(self):
        handler = server_module.ParkingHandler.__new__(server_module.ParkingHandler)
        handler.headers = {}
        handler.rfile = io.BytesIO()
        handler.wfile = io.BytesIO()
        handler.sent_response = None
        handler.sent_headers = {}
        handler.redirected_to = None
        handler.rendered_html = None
        handler.error_status = None
        handler.send_response = lambda status: setattr(handler, "sent_response", status)
        handler.send_header = lambda key, value: handler.sent_headers.__setitem__(key, value)
        handler.end_headers = lambda: None
        handler.redirect = lambda location, cookie=None: setattr(handler, "redirected_to", location)
        handler.render_html = lambda html: setattr(handler, "rendered_html", html)
        handler.send_error = lambda status: setattr(handler, "error_status", status)
        return handler

    def test_banners_page_requires_authentication(self) -> None:
        handler = self.make_handler()
        handler.path = "/banners"
        handler.current_user = lambda: None
        handler.do_GET()
        self.assertEqual(handler.redirected_to, "/login")

    def test_banner_validation_errors_render_back_to_form(self) -> None:
        handler = self.make_handler()
        handler.parse_request_data = lambda: (
            {
                "template_set_id": "leasingmarkt-core-campaign",
                "headline": "X" * 60,
                "subline": "Still valid",
                "button_text": "Click",
            },
            {"image_upload": {"filename": "hero.png", "content_type": "image/png", "body": make_image_bytes()}},
        )
        current_user = server_module.REPO.get_user(1)
        handler.handle_banner_generate(current_user)
        self.assertIn("Headline must be 42 characters or fewer.", handler.rendered_html)

    def test_successful_banner_generation_can_be_downloaded(self) -> None:
        current_user = server_module.REPO.get_user(1)
        run_id = server_module.BANNER_SERVICE.generate_banner_run(
            user_id=current_user["id"],
            template_set_id="leasingmarkt-core-campaign",
            headline="Banner headline",
            subline="A valid supporting subline for the campaign banner.",
            button_text="Start now",
            image=UploadedBannerImage("hero.png", "image/png", make_image_bytes()),
        )
        handler = self.make_handler()
        handler.handle_banner_download(current_user, run_id)
        self.assertEqual(handler.sent_response, 200)
        self.assertEqual(handler.sent_headers["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(handler.wfile.getvalue())) as archive:
            self.assertIn("manifest.json", archive.namelist())


if __name__ == "__main__":
    unittest.main()
