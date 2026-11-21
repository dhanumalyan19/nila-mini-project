import pytest


def pytest_addoption(parser):
    parser.addoption("--mysql-integration", action="store_true", help="Start an isolated temporary MySQL Server for real database tests.")


@pytest.fixture(scope="session")
def mysql_settings(request):
    if not request.config.getoption("--mysql-integration"):
        pytest.skip("Real MySQL tests are opt-in: pass --mysql-integration.")
    from mysql_server import disposable_mysql
    with disposable_mysql() as settings:
        yield settings

