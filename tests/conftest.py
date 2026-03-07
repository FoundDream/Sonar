import pytest


def pytest_addoption(parser):
    parser.addoption("--run-network", action="store_true", default=False, help="运行需要网络的测试")


def pytest_configure(config):
    config.addinivalue_line("markers", "network: 需要网络访问的测试")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip = pytest.mark.skip(reason="需要 --run-network 参数")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
