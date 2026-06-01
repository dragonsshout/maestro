"""
Tests for integration clients.
Covers: GithubIntegration, JenkinsIntegration.
Uses httpx mock responses to simulate external API calls.
"""
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from maestro.integration.github import GithubIntegration
from maestro.integration.jenkins import JenkinsIntegration
from maestro.schemas.github import PullRequestSchema, PullRequestDetailSchema
from maestro.schemas.jenkins import JenkinsQueueItemSchema


# ===========================================================================
# GithubIntegration
# ===========================================================================

class TestGithubIntegration:
    @pytest.fixture
    def github(self):
        return GithubIntegration(organization="my-org", token="ghp_test_token")

    def test_init(self, github):
        assert github.organization == "my-org"
        assert github.token == "ghp_test_token"
        assert github.base_url == "https://api.github.com"

    def test_init_without_token(self):
        gh = GithubIntegration(organization="org")
        assert gh.token is None

    async def test_branch_exists_true(self, github):
        mock_response = httpx.Response(200)
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await github.branch_exists("my-repo", "feature/branch")
            assert result is True

    async def test_branch_exists_false(self, github):
        mock_response = httpx.Response(404)
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await github.branch_exists("my-repo", "nonexistent")
            assert result is False

    async def test_branch_exists_other_status(self, github):
        mock_response = httpx.Response(500)
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await github.branch_exists("my-repo", "branch")
            assert result is False

    async def test_get_pull_request_details(self, github):
        pr_data = {
            "number": 42,
            "state": "open",
            "title": "My PR",
            "mergeable_state": "clean",
            "mergeable": True,
        }
        mock_response = httpx.Response(200, json=pr_data, request=httpx.Request("GET", "http://test"))
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await github.get_pull_request_details("my-repo", 42)
            assert isinstance(result, PullRequestDetailSchema)
            assert result.number == 42
            assert result.mergeable_state == "clean"
            assert result.mergeable is True

    async def test_get_pull_request_details_http_error(self, github):
        mock_response = httpx.Response(404, request=httpx.Request("GET", "http://test"))
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            with pytest.raises(httpx.HTTPStatusError):
                await github.get_pull_request_details("my-repo", 999)

    async def test_get_pull_request_by_branch_found(self, github):
        pr_data = [{"number": 10, "state": "open", "title": "Feature PR"}]
        mock_response = httpx.Response(200, json=pr_data, request=httpx.Request("GET", "http://test"))
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await github.get_pull_request_by_branch("my-repo", "feature/x")
            assert isinstance(result, PullRequestSchema)
            assert result.number == 10

    async def test_get_pull_request_by_branch_not_found(self, github):
        mock_response = httpx.Response(200, json=[], request=httpx.Request("GET", "http://test"))
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await github.get_pull_request_by_branch("my-repo", "no-branch")
            assert result is None

    async def test_get_pull_request_by_branch_http_error(self, github):
        mock_response = httpx.Response(500, request=httpx.Request("GET", "http://test"))
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            with pytest.raises(httpx.HTTPStatusError):
                await github.get_pull_request_by_branch("my-repo", "feature/x")

    def test_get_client_with_token(self, github):
        client = github._get_client()
        assert client is not None

    def test_get_client_without_token(self):
        gh = GithubIntegration(organization="org")
        client = gh._get_client()
        assert client is not None


# ===========================================================================
# JenkinsIntegration
# ===========================================================================

class TestJenkinsIntegration:
    @pytest.fixture
    def jenkins(self):
        return JenkinsIntegration(
            base_url="http://jenkins.local:8080",
            username="admin",
            token="jenkins-token",
        )

    def test_init(self, jenkins):
        assert jenkins.base_url == "http://jenkins.local:8080"
        assert jenkins.username == "admin"
        assert jenkins.token == "jenkins-token"

    def test_init_strips_trailing_slash(self):
        j = JenkinsIntegration(base_url="http://jenkins:8080/")
        assert j.base_url == "http://jenkins:8080"

    def test_init_no_auth(self):
        j = JenkinsIntegration(base_url="http://jenkins:8080")
        assert j.username is None
        assert j.token is None

    async def test_job_exists_true(self, jenkins):
        mock_response = httpx.Response(200)
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await jenkins.job_exists("job/my-deploy")
            assert result is True

    async def test_job_exists_false(self, jenkins):
        mock_response = httpx.Response(404)
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await jenkins.job_exists("job/nonexistent")
            assert result is False

    async def test_trigger_job_and_get_queue_url_with_params(self, jenkins):
        mock_response = httpx.Response(
            201,
            headers={"Location": "http://jenkins.local:8080/queue/item/123/"},
        )
        with patch.object(httpx.AsyncClient, "post", return_value=mock_response):
            result = await jenkins.trigger_job_and_get_queue_url(
                "job/deploy", parameters={"BRANCH": "main"}
            )
            assert result == "http://jenkins.local:8080/queue/item/123/"

    async def test_trigger_job_and_get_queue_url_without_params(self, jenkins):
        mock_response = httpx.Response(
            201,
            headers={"Location": "http://jenkins.local:8080/queue/item/456/"},
        )
        with patch.object(httpx.AsyncClient, "post", return_value=mock_response):
            result = await jenkins.trigger_job_and_get_queue_url("job/deploy")
            assert "queue/item/456" in result

    async def test_trigger_job_no_location_header(self, jenkins):
        mock_response = httpx.Response(201, headers={})
        with patch.object(httpx.AsyncClient, "post", return_value=mock_response):
            with pytest.raises(ValueError, match="Location"):
                await jenkins.trigger_job_and_get_queue_url("job/deploy")

    async def test_trigger_job_error_status(self, jenkins):
        mock_response = httpx.Response(500, request=httpx.Request("POST", "http://test"))
        with patch.object(httpx.AsyncClient, "post", return_value=mock_response):
            with pytest.raises(httpx.HTTPStatusError):
                await jenkins.trigger_job_and_get_queue_url("job/deploy")

    async def test_get_queue_item_info_with_executable(self, jenkins):
        queue_data = {"executable": {"number": 42}}
        mock_response = httpx.Response(200, json=queue_data, request=httpx.Request("GET", "http://test"))
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await jenkins.get_queue_item_info("/queue/item/123")
            assert isinstance(result, JenkinsQueueItemSchema)
            assert result.executable.number == 42

    async def test_get_queue_item_info_without_executable(self, jenkins):
        queue_data = {"executable": None}
        mock_response = httpx.Response(200, json=queue_data, request=httpx.Request("GET", "http://test"))
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response):
            result = await jenkins.get_queue_item_info("/queue/item/123")
            assert result.executable is None

    async def test_get_queue_item_info_strips_base_url(self, jenkins):
        """If queue_url contains base_url, it should be stripped."""
        queue_data = {"executable": {"number": 10}}
        mock_response = httpx.Response(200, json=queue_data, request=httpx.Request("GET", "http://test"))
        with patch.object(httpx.AsyncClient, "get", return_value=mock_response) as mock_get:
            full_url = "http://jenkins.local:8080/queue/item/999"
            result = await jenkins.get_queue_item_info(full_url)
            assert result.executable.number == 10

    async def test_approve_pipeline_with_input_id(self, jenkins):
        mock_response = httpx.Response(200)
        with patch.object(httpx.AsyncClient, "post", return_value=mock_response):
            # Should not raise
            await jenkins.approve_pipeline("job/deploy", build_number=10, input_id="my-input")

    async def test_approve_pipeline_without_input_id_fetches_pending(self, jenkins):
        # First call returns pending input actions
        pending_response_data = [
            {"id": "auto-discovered-id", "inputs": [{"name": "APPROVAL"}]}
        ]
        mock_get_response = httpx.Response(200, json=pending_response_data)
        mock_post_response = httpx.Response(200)

        with patch.object(httpx.AsyncClient, "get", return_value=mock_get_response):
            with patch.object(httpx.AsyncClient, "post", return_value=mock_post_response):
                await jenkins.approve_pipeline("job/deploy", build_number=10)

    async def test_approve_pipeline_error_status(self, jenkins):
        mock_response = httpx.Response(500, request=httpx.Request("POST", "http://test"))
        with patch.object(httpx.AsyncClient, "post", return_value=mock_response):
            with patch.object(httpx.AsyncClient, "get", return_value=httpx.Response(200, json=[])):
                with pytest.raises(httpx.HTTPStatusError):
                    await jenkins.approve_pipeline("job/deploy", build_number=10, input_id="inp")
