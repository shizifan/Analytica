import os

import pytest
from dotenv import load_dotenv

# Load .env from project root BEFORE any test modules import
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

pytest_plugins = [
    "tests.fixtures.mock_server",
    "tests.fixtures.mock_data",
]
