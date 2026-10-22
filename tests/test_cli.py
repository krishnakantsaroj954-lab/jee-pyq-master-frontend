import pytest
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import signal
import json

from jee_pyq_pipeline.cli import _build_batch
from jee_pyq_pipeline.models import Issue

def test_build_batch_timeout_degrades_gracefully(tmp_path):
    dummy_pdf = tmp_path / 'dummy.pdf'
    dummy_pdf.write_bytes(b'dummy pdf content')

    config = SimpleNamespace(
        source_pdf=dummy_pdf,
        source_has_solutions=False,
        exam="JEE-MAIN",
        year=2026,
        session="Test",
        paper="Test",
        subject="Physics",
        release="r1",
        page_range=(1, 1),
        source_zip=None,
        review_manifest=None
    )

    output_dir = tmp_path / 'output'

    def mock_extract(*args, **kwargs):
        raise TimeoutError("Extraction exceeded 1 seconds")

    with patch('jee_pyq_pipeline.cli.extract', side_effect=mock_extract):
        with patch('jee_pyq_pipeline.cli.validate', return_value=[]):
            status = _build_batch(config, output_dir, timeout_seconds=1)

            # Check graceful degradation
            assert status == 'QUARANTINED'

            report_file = output_dir / 'validation-report.json'
            assert report_file.exists()

            report = json.loads(report_file.read_text())
            assert report['status'] == 'QUARANTINED'

            # The exception should be converted to a blocking issue
            assert report['blocking_issue_count'] >= 1
            timeout_issues = [i for i in report['issues'] if i.get('code') == 'EXTRACTION_TIMEOUT']
            assert len(timeout_issues) == 1
            assert timeout_issues[0]['message'] == 'Extraction exceeded 1 seconds'
            assert timeout_issues[0]['blocking'] is True
