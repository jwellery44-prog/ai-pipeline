import unittest
from unittest.mock import MagicMock, patch
import httpx

# Mock Settings environment variables before importing app
with patch.dict("os.environ", {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV4YW1wbGUiLCJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNjAwMDAwMDAwLCJleHAiOjE5MDAwMDAwMDB9.fake-signature",
    "REVE_API_KEY": "fake-reve-key",
    "NANOBANA_API_KEY": "fake-nanobana-key",
    "DAILY_UPLOAD_LIMIT": "2",  # Set limit to 2 for testing
}):
    from app.main import app
    from app.config import settings

class TestDailyUploadLimit(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    @patch("app.db.repository.get_supabase")
    @patch("app.main.upload_raw_image")
    @patch("app.main.update_product_image_url")
    @patch("app.main._run_product_pipeline")
    async def test_upload_usage_endpoints(self, mock_pipeline, mock_update_img_url, mock_upload_raw, mock_get_supabase):
        # Setup mock Supabase execute response for daily count
        mock_response = MagicMock()
        mock_response.count = 1
        
        # Build self-returning query chain mock
        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.execute.return_value = mock_response
        
        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_query
        mock_get_supabase.return_value = mock_supabase

        # Test GET /api/upload-usage with no wholesaler_id
        response = await self.client.get("/api/upload-usage")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["used"], 1)
        self.assertEqual(data["limit"], 2)
        self.assertEqual(data["remaining"], 1)

        # Test GET /api/upload-usage with wholesaler_id
        response = await self.client.get("/api/upload-usage?wholesaler_id=wh-test")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["used"], 1)

    @patch("app.db.repository.get_supabase")
    @patch("app.main.upload_raw_image")
    @patch("app.main.update_product_image_url")
    @patch("app.main._run_product_pipeline")
    async def test_process_upload_limit_gate(self, mock_pipeline, mock_update_img_url, mock_upload_raw, mock_get_supabase):
        # 1. Mock daily count to be 1 (under the limit of 2)
        mock_count_response = MagicMock()
        mock_count_response.count = 1
        
        # 2. Mock create_product / insert response
        mock_insert_product_resp = MagicMock()
        mock_insert_product_resp.data = [{"id": "fb6f6b55-ee5e-49b8-a6d1-817865cbb685", "title": "Test Ring"}]

        # 3. Mock log_pipeline_trigger / insert response
        mock_insert_log_resp = MagicMock()
        mock_insert_log_resp.data = [{"id": "fake-log-uuid-1"}]

        # Build self-returning query chain mock
        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.execute.return_value = mock_count_response
        
        # Build insert mocks
        mock_insert_product = MagicMock()
        mock_insert_product.execute.return_value = mock_insert_product_resp

        mock_insert_log = MagicMock()
        mock_insert_log.execute.return_value = mock_insert_log_resp
        
        def table_side_effect(table_name):
            t = MagicMock()
            if table_name == "images":
                t.insert.return_value = mock_insert_product
                t.select.return_value = mock_query
            elif table_name == "ai_generation_logs":
                t.insert.return_value = mock_insert_log
                t.select.return_value = mock_query
                t.update.return_value = t
                t.eq.return_value = t
                t.execute.return_value = MagicMock(data=[])
            return t
            
        mock_supabase = MagicMock()
        mock_supabase.table.side_effect = table_side_effect
        mock_get_supabase.return_value = mock_supabase
        mock_upload_raw.return_value = "https://example.com/test.jpg"

        # First request: limit is 2, count is 1. Should succeed (accept 202).
        files = {"file": ("test.jpg", b"fake image content", "image/jpeg")}
        data = {"title": "Test Ring", "wholesaler_id": "wh-test"}
        
        response = await self.client.post("/process", data=data, files=files)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["product_id"], "fb6f6b55-ee5e-49b8-a6d1-817865cbb685")

        # Now, change mock count response to return 2 (limit reached)
        mock_count_response.count = 2
        response = await self.client.post("/process", data=data, files=files)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Daily upload limit reached", response.json()["detail"]["message"])

    @patch("app.db.repository.get_supabase")
    @patch("app.main._run_product_pipeline")
    async def test_process_existing_image_limit_gate(self, mock_pipeline, mock_get_supabase):
        mock_supabase = MagicMock()
        
        # Mock select response for fetch_job_by_id (return existing product)
        mock_select_job_exec = MagicMock()
        mock_select_job_exec.data = [{
            "id": "fb6f6b55-ee5e-49b8-a6d1-817865cbb685",
            "title": "Test Ring",
            "image_url": "https://example.com/test.jpg",
            "wholesaler_id": "wh-test"
        }]
        
        mock_select_job = MagicMock()
        mock_select_job.eq.return_value.limit.return_value.execute.return_value = mock_select_job_exec

        # Mock count check to return 2 (limit reached)
        mock_count = MagicMock()
        mock_count_exec = MagicMock()
        mock_count_exec.count = 2
        mock_count.eq.return_value.gte.return_value.lt.return_value.eq.return_value.execute.return_value = mock_count_exec
        mock_count.eq.return_value.gte.return_value.lt.return_value.execute.return_value = mock_count_exec

        # Mock log insert for trigger
        mock_insert_log = MagicMock()
        mock_insert_log.execute.return_value = MagicMock(data=[{"id": "fake-log-uuid-2"}])

        def table_side_effect(table_name):
            t = MagicMock()
            if table_name == "images":
                t.select = MagicMock(return_value=mock_select_job)
                t.update = MagicMock(return_value=t)
                t.eq = MagicMock(return_value=t)
                t.execute = MagicMock(return_value=MagicMock(data=[]))
            elif table_name == "ai_generation_logs":
                t.select = MagicMock(return_value=mock_count)
                t.insert.return_value = mock_insert_log
                t.update = MagicMock(return_value=t)
                t.eq = MagicMock(return_value=t)
                t.execute = MagicMock(return_value=MagicMock(data=[]))
            return t

        mock_supabase.table.side_effect = table_side_effect
        mock_get_supabase.return_value = mock_supabase

        # Try to reprocess: should return 429 because count is 2
        response = await self.client.post("/process/fb6f6b55-ee5e-49b8-a6d1-817865cbb685")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Daily upload limit reached", response.json()["detail"]["message"])

    @patch("app.main.get_upload_history")
    async def test_upload_history_endpoint(self, mock_get_history):
        mock_get_history.return_value = [
            {
                "log_id": "log-uuid-1",
                "product_id": "prod-uuid-1",
                "trigger_source": "new_upload",
                "log_status": "success",
                "triggered_at": "2026-06-22T00:15:44Z",
                "completed_at": "2026-06-22T00:16:15Z",
                "title": "Diamond Ring",
                "image_url": "https://example.com/test.jpg",
                "is_reuploaded": False
            }
        ]

        response = await self.client.get("/api/upload-history?wholesaler_id=wh-test&limit=10&start_date=2026-06-22T00:00:00Z")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Diamond Ring")
        self.assertEqual(data[0]["is_reuploaded"], False)
        mock_get_history.assert_called_once_with(wholesaler_id="wh-test", limit=10, start_date="2026-06-22T00:00:00Z")

    @patch("app.db.repository.get_supabase")
    async def test_get_upload_history_db(self, mock_get_supabase):
        mock_response = MagicMock()
        mock_response.data = [{
            "id": "log-uuid-1",
            "product_id": "prod-uuid-1",
            "triggered_at": "2026-06-22T00:15:44Z",
            "completed_at": "2026-06-22T00:16:15Z",
            "status": "success",
            "trigger_source": "new_upload",
            "products": {
                "title": "Diamond Ring",
                "image_url": "https://example.com/test.jpg"
            }
        }]

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.execute.return_value = mock_response

        mock_supabase = MagicMock()
        mock_supabase.table.return_value = mock_query
        mock_get_supabase.return_value = mock_supabase

        from app.db.repository import get_upload_history
        history = await get_upload_history(wholesaler_id="wh-test", limit=5, start_date="2026-06-22T00:00:00Z")
        
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["title"], "Diamond Ring")
        self.assertEqual(history[0]["image_url"], "https://example.com/test.jpg")
        self.assertEqual(history[0]["is_reuploaded"], False)
        mock_supabase.table.assert_called_once_with("ai_generation_logs")
        mock_query.gte.assert_called_once_with("triggered_at", "2026-06-22T00:00:00Z")

if __name__ == "__main__":
    unittest.main()
