"""UCP merchant discovery and repeatable REST requests."""
from .client import UCP_VERSION, PreparedRequest, Result, UcpClient, UcpError, select_capabilities

__version__ = "0.1.0"
__all__ = ["UCP_VERSION", "PreparedRequest", "Result", "UcpClient", "UcpError", "select_capabilities"]
