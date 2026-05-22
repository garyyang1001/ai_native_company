import unittest
import threading
from urllib.request import urlopen

from closed_loop_kernel.http_app import build_demo_store, route_post, route_request, serve


class HttpAppTests(unittest.TestCase):
    def setUp(self):
        self.store = build_demo_store()

    def test_routes_render_the_four_specified_views(self):
        for path, expected in [
            ("/events", "事件紀錄"),
            ("/improvements", "修正案"),
            ("/approvals", "等待審核"),
        ]:
            response = route_request(self.store, path)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, "text/html; charset=utf-8")
            self.assertIn(expected, response.body)

    def test_event_detail_route_renders_attempt_timeline(self):
        attempt_id = self.store.scalar("SELECT id FROM attempts ORDER BY created_at LIMIT 1")

        response = route_request(self.store, f"/events/{attempt_id}")

        self.assertEqual(response.status, 200)
        self.assertIn("執行詳情", response.body)
        self.assertIn("執行失敗", response.body)
        self.assertNotIn("Attempt ", response.body)
        self.assertNotIn("Status:", response.body)
        self.assertNotIn("Tool Calls", response.body)

    def test_unknown_route_returns_404(self):
        response = route_request(self.store, "/missing")

        self.assertEqual(response.status, 404)
        self.assertIn("Not Found", response.body)

    def test_post_approval_approve_applies_candidate(self):
        candidate_id = self.store.scalar("SELECT id FROM improvement_candidates LIMIT 1")

        response = route_post(self.store, f"/approvals/{candidate_id}/approve")

        self.assertEqual(response.status, 303)
        self.assertEqual(self.store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [candidate_id]), "applied")
        self.assertEqual(self.store.scalar("SELECT status FROM failures LIMIT 1"), "resolved")
        event_types = [row["event_type"] for row in self.store.fetch_all("SELECT event_type FROM events ORDER BY created_at")]
        self.assertIn("approval_granted", event_types)
        self.assertIn("candidate_applied", event_types)
        self.assertIn("目前沒有待審核修正案", route_request(self.store, "/approvals").body)
        self.assertIn("applied", response.body)

    def test_post_approval_reject_records_rejection(self):
        candidate_id = self.store.scalar("SELECT id FROM improvement_candidates LIMIT 1")

        response = route_post(self.store, f"/approvals/{candidate_id}/reject")

        self.assertEqual(response.status, 303)
        self.assertEqual(self.store.scalar("SELECT status FROM improvement_candidates WHERE id = ?", [candidate_id]), "rejected")
        self.assertEqual(self.store.scalar("SELECT decision FROM approvals WHERE candidate_id = ?", [candidate_id]), "rejected")
        self.assertEqual(self.store.scalar("SELECT status FROM failures LIMIT 1"), "open")
        self.assertIn("rejected", response.body)

    def test_favicon_route_is_empty_success_to_avoid_browser_console_noise(self):
        response = route_request(self.store, "/favicon.ico")

        self.assertEqual(response.status, 204)
        self.assertEqual(response.body, "")

    def test_real_http_server_serves_events_route(self):
        server = serve(port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            with urlopen(f"http://{host}:{port}/events", timeout=2) as response:
                body = response.read().decode("utf-8")
            self.assertIn("事件紀錄", body)
            self.assertIn("任務開始", body)
            self.assertNotIn("attempt_lifecycle_events", body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
