from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from maestro.main import app
from maestro.schemas.github import PullRequestSchema, PullRequestDetailSchema

client = TestClient(app)

SAMPLE_YAML = """
apiVersion: v1
kind: Release
metadata:
  name: test-release
  author: tester
  description: Test release
spec:
  stages:
    - id: stage-1
      steps:
        - id: step-1
          repository: my-repo
          release: feature/branch-1
          job:
            type: jenkins
            path: job/path/deploy
"""


def _mock_descriptor(name="test-release"):
    descriptor = MagicMock()
    descriptor.name = name
    descriptor.yaml = SAMPLE_YAML
    return descriptor


@patch("maestro.services.orchestrator.JenkinsIntegration")
@patch("maestro.services.orchestrator.GithubIntegration")
@patch("maestro.services.orchestrator.OrchestratorService.__init__", return_value=None)
@patch("maestro.services.orchestrator.OrchestratorService.dry_run_release")
def test_dry_run_descriptor_not_found(mock_dry_run, mock_init, mock_github, mock_jenkins):
    """Descriptor not found returns 400."""
    mock_dry_run.side_effect = ValueError("Descritor com nome 'nonexistent' não encontrado.")

    response = client.post("/orchestrator/dry-run", json={"name": "nonexistent"})
    assert response.status_code == 400
    assert "não encontrado" in response.json()["detail"]


@patch("maestro.services.app_settings.get_integration_settings")
@patch("maestro.services.orchestrator.JenkinsIntegration")
@patch("maestro.services.orchestrator.GithubIntegration")
@patch.object(
    __import__("maestro.repositories.orchestrator", fromlist=["OrchestratorDescriptorRepository"]).OrchestratorDescriptorRepository,
    "get_by_name",
    new_callable=AsyncMock,
)
def test_dry_run_all_validations_pass(mock_get_by_name, mock_github_cls, mock_jenkins_cls, mock_get_settings):
    """All validations pass returns valid=true."""
    mock_get_settings.return_value = MagicMock(
        github_organization="org", github_token="t", github_base_url=None, http_trust_env=True,
        jenkins_url="http://j:8080", jenkins_username="u", jenkins_token="t",
    )
    mock_get_by_name.return_value = _mock_descriptor()

    mock_github_instance = AsyncMock()
    mock_github_instance.branch_exists.return_value = True
    mock_github_instance.get_pull_request_by_branch.return_value = PullRequestSchema(
        number=42, state="open", title="Feature PR"
    )
    mock_github_instance.get_pull_request_details.return_value = PullRequestDetailSchema(
        number=42, state="open", title="Feature PR", mergeable_state="clean", mergeable=True
    )
    mock_github_cls.return_value = mock_github_instance

    mock_jenkins_instance = AsyncMock()
    mock_jenkins_instance.job_exists.return_value = True
    mock_jenkins_cls.return_value = mock_jenkins_instance

    response = client.post("/orchestrator/dry-run", json={"name": "test-release"})
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["name"] == "test-release"
    assert len(data["stages"]) == 1
    step = data["stages"][0]["steps"][0]
    assert step["branch_exists"] is True
    assert step["pr_found"] is True
    assert step["pr_number"] == 42
    assert step["pr_mergeable_state"] == "clean"
    assert step["pr_is_clean"] is True
    assert step["jenkins_job_exists"] is True


@patch("maestro.services.app_settings.get_integration_settings")
@patch("maestro.services.orchestrator.JenkinsIntegration")
@patch("maestro.services.orchestrator.GithubIntegration")
@patch.object(
    __import__("maestro.repositories.orchestrator", fromlist=["OrchestratorDescriptorRepository"]).OrchestratorDescriptorRepository,
    "get_by_name",
    new_callable=AsyncMock,
)
def test_dry_run_branch_not_found(mock_get_by_name, mock_github_cls, mock_jenkins_cls, mock_get_settings):
    """Branch not found returns valid=false with branch_exists=false."""
    mock_get_settings.return_value = MagicMock(
        github_organization="org", github_token="t", github_base_url=None, http_trust_env=True,
        jenkins_url="http://j:8080", jenkins_username="u", jenkins_token="t",
    )
    mock_get_by_name.return_value = _mock_descriptor()

    mock_github_instance = AsyncMock()
    mock_github_instance.branch_exists.return_value = False
    mock_github_instance.get_pull_request_by_branch.return_value = None
    mock_github_cls.return_value = mock_github_instance

    mock_jenkins_instance = AsyncMock()
    mock_jenkins_instance.job_exists.return_value = True
    mock_jenkins_cls.return_value = mock_jenkins_instance

    response = client.post("/orchestrator/dry-run", json={"name": "test-release"})
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    step = data["stages"][0]["steps"][0]
    assert step["branch_exists"] is False


@patch("maestro.services.app_settings.get_integration_settings")
@patch("maestro.services.orchestrator.JenkinsIntegration")
@patch("maestro.services.orchestrator.GithubIntegration")
@patch.object(
    __import__("maestro.repositories.orchestrator", fromlist=["OrchestratorDescriptorRepository"]).OrchestratorDescriptorRepository,
    "get_by_name",
    new_callable=AsyncMock,
)
def test_dry_run_pr_not_found(mock_get_by_name, mock_github_cls, mock_jenkins_cls, mock_get_settings):
    """PR not found returns valid=false with pr_found=false."""
    mock_get_settings.return_value = MagicMock(
        github_organization="org", github_token="t", github_base_url=None, http_trust_env=True,
        jenkins_url="http://j:8080", jenkins_username="u", jenkins_token="t",
    )
    mock_get_by_name.return_value = _mock_descriptor()

    mock_github_instance = AsyncMock()
    mock_github_instance.branch_exists.return_value = True
    mock_github_instance.get_pull_request_by_branch.return_value = None
    mock_github_cls.return_value = mock_github_instance

    mock_jenkins_instance = AsyncMock()
    mock_jenkins_instance.job_exists.return_value = True
    mock_jenkins_cls.return_value = mock_jenkins_instance

    response = client.post("/orchestrator/dry-run", json={"name": "test-release"})
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    step = data["stages"][0]["steps"][0]
    assert step["branch_exists"] is True
    assert step["pr_found"] is False


@patch("maestro.services.app_settings.get_integration_settings")
@patch("maestro.services.orchestrator.JenkinsIntegration")
@patch("maestro.services.orchestrator.GithubIntegration")
@patch.object(
    __import__("maestro.repositories.orchestrator", fromlist=["OrchestratorDescriptorRepository"]).OrchestratorDescriptorRepository,
    "get_by_name",
    new_callable=AsyncMock,
)
def test_dry_run_pr_not_clean(mock_get_by_name, mock_github_cls, mock_jenkins_cls, mock_get_settings):
    """PR not clean returns valid=false with correct mergeable_state."""
    mock_get_settings.return_value = MagicMock(
        github_organization="org", github_token="t", github_base_url=None, http_trust_env=True,
        jenkins_url="http://j:8080", jenkins_username="u", jenkins_token="t",
    )
    mock_get_by_name.return_value = _mock_descriptor()

    mock_github_instance = AsyncMock()
    mock_github_instance.branch_exists.return_value = True
    mock_github_instance.get_pull_request_by_branch.return_value = PullRequestSchema(
        number=10, state="open", title="Feature PR"
    )
    mock_github_instance.get_pull_request_details.return_value = PullRequestDetailSchema(
        number=10, state="open", title="Feature PR", mergeable_state="dirty", mergeable=False
    )
    mock_github_cls.return_value = mock_github_instance

    mock_jenkins_instance = AsyncMock()
    mock_jenkins_instance.job_exists.return_value = True
    mock_jenkins_cls.return_value = mock_jenkins_instance

    response = client.post("/orchestrator/dry-run", json={"name": "test-release"})
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    step = data["stages"][0]["steps"][0]
    assert step["pr_found"] is True
    assert step["pr_number"] == 10
    assert step["pr_mergeable_state"] == "dirty"
    assert step["pr_is_clean"] is False


@patch("maestro.services.app_settings.get_integration_settings")
@patch("maestro.services.orchestrator.JenkinsIntegration")
@patch("maestro.services.orchestrator.GithubIntegration")
@patch.object(
    __import__("maestro.repositories.orchestrator", fromlist=["OrchestratorDescriptorRepository"]).OrchestratorDescriptorRepository,
    "get_by_name",
    new_callable=AsyncMock,
)
def test_dry_run_jenkins_job_not_found(mock_get_by_name, mock_github_cls, mock_jenkins_cls, mock_get_settings):
    """Jenkins job not found returns valid=false with jenkins_job_exists=false."""
    mock_get_settings.return_value = MagicMock(
        github_organization="org", github_token="t", github_base_url=None, http_trust_env=True,
        jenkins_url="http://j:8080", jenkins_username="u", jenkins_token="t",
    )
    mock_get_by_name.return_value = _mock_descriptor()

    mock_github_instance = AsyncMock()
    mock_github_instance.branch_exists.return_value = True
    mock_github_instance.get_pull_request_by_branch.return_value = PullRequestSchema(
        number=42, state="open", title="Feature PR"
    )
    mock_github_instance.get_pull_request_details.return_value = PullRequestDetailSchema(
        number=42, state="open", title="Feature PR", mergeable_state="clean", mergeable=True
    )
    mock_github_cls.return_value = mock_github_instance

    mock_jenkins_instance = AsyncMock()
    mock_jenkins_instance.job_exists.return_value = False
    mock_jenkins_cls.return_value = mock_jenkins_instance

    response = client.post("/orchestrator/dry-run", json={"name": "test-release"})
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    step = data["stages"][0]["steps"][0]
    assert step["branch_exists"] is True
    assert step["pr_found"] is True
    assert step["pr_is_clean"] is True
    assert step["jenkins_job_exists"] is False
