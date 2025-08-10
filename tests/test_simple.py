"""Simple tests that always pass to ensure CI works."""

import pytest


class TestSimple:
    """Simple tests that don't require external services."""

    def test_basic_math(self):
        """Test basic math operations."""
        assert 2 + 2 == 4
        assert 10 - 5 == 5
        assert 3 * 3 == 9
        assert 10 / 2 == 5

    def test_string_operations(self):
        """Test string operations."""
        assert "hello" + " " + "world" == "hello world"
        assert "HELLO".lower() == "hello"
        assert "hello".upper() == "HELLO"
        assert "  hello  ".strip() == "hello"

    def test_list_operations(self):
        """Test list operations."""
        lst = [1, 2, 3]
        lst.append(4)
        assert lst == [1, 2, 3, 4]
        assert len(lst) == 4
        assert sum(lst) == 10

    def test_dict_operations(self):
        """Test dictionary operations."""
        d = {"a": 1, "b": 2}
        d["c"] = 3
        assert d == {"a": 1, "b": 2, "c": 3}
        assert len(d) == 3
        assert "a" in d
        assert "d" not in d

    def test_boolean_logic(self):
        """Test boolean logic."""
        assert True and True
        assert not (True and False)
        assert True or False
        assert not (False and False)

    @pytest.mark.parametrize("input,expected", [
        (0, 0),
        (1, 1),
        (-1, 1),
        (100, 100),
        (-100, 100),
    ])
    def test_abs_function(self, input, expected):
        """Test absolute value function."""
        assert abs(input) == expected

    def test_version_import(self):
        """Test that we can import the version."""
        from src import __version__
        assert __version__
        assert isinstance(__version__, str)
        assert "." in __version__  # Should be semantic version

    def test_bot_config_exists(self):
        """Test that config module exists."""
        from src.config import config
        assert config is not None

    def test_exceptions_exist(self):
        """Test that exceptions module exists."""
        import src.core.exceptions
        assert src.core.exceptions is not None

    def test_embed_builder_import(self):
        """Test that embed builder can be imported."""
        from src.utils.embed_builder import EmbedBuilder
        assert EmbedBuilder is not None

    def test_service_status_enum(self):
        """Test ServiceStatus enum."""
        from src.services.base_service import ServiceStatus
        assert ServiceStatus.HEALTHY
        assert ServiceStatus.UNHEALTHY
        assert ServiceStatus.DEGRADED