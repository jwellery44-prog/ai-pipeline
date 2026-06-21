import unittest
from unittest.mock import MagicMock, patch
import httpx

# Mock Settings environment variables before importing app
with patch.dict("os.environ", {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV4YW1wbGUiLCJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNjAwMDAwMDAwLCJleHAiOjE5MDAwMDAwMDB9.fake-signature", # Valid format JWT to bypass client validation
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
        
        # Build chain mock
        mock_query = MagicMock()
        mock_query.execute.return_value = mock_response
        mock_query.eq.return_value = mock_query
        
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.not_.is_.return_value.gte.return_value.lt.return_value = mock_query
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
        mock_insert_response = MagicMock()
        mock_insert_response.data = [{"id": "fb6f6b55-ee5e-49b8-a6d1-817865cbb685", "title": "Test Ring"}]

        mock_supabase = MagicMock()
        
        # Build daily count chain
        mock_select = MagicMock()
        mock_select.not_.is_.return_value.gte.return_value.lt.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.execute.return_value = mock_count_response
        
        # Build insert chain
        mock_insert = MagicMock()
        mock_insert.execute.return_value = mock_insert_response
        
        def table_side_effect(table_name):
            t = MagicMock()
            t.select = MagicMock(return_value=mock_select)
            t.insert = MagicMock(return_value=mock_insert)
            t.update = MagicMock(return_value=t)
            t.eq = MagicMock(return_value=t)
            t.execute = MagicMock(return_value=MagicMock(data=[]))
            return t
            
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
        mock_count.not_.is_.return_value.gte.return_value.lt.return_value.eq.return_value.execute.return_value = mock_count_exec
        mock_count.not_.is_.return_value.gte.return_value.lt.return_value.execute.return_value = mock_count_exec

        def table_side_effect(table_name):
            t = MagicMock()
            
            # Simple dispatcher depending on select args
            def select_dispatcher(*args, **kwargs):
                if len(args) > 0 and (args[0] == "*" or args[0] == "id" and "count" not in kwargs):
                    return mock_select_job
                return mock_count

            t.select = MagicMock(side_effect=select_dispatcher)
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

if __name__ == "__main__":
    unittest.main()
