
import uuid
from enum import Enum
from typing import Any

from pydantic.v1 import BaseModel, Field


class AgentRole(str,Enum):
    """Enum representing the roles."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

class SecurityContext(BaseModel):
    """Class representing the security context."""
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    session_id: str 
    permissions: list[str] = Field(default_factory=list)
    rate_limit_tier: str = "standard"

class AgentRequest(BaseModel):
    """Class representing the agent request."""
    raw_input: str
    security_context: SecurityContext
    max_token: int = 1024
    temperature: float = 0.1
    metadata: dict[str,Any] = Field(default_factory=dict)

class AgentResponse(BaseModel):
    """Class representing the agent response."""
    request_id: str
    content: str
    tool_calls: list[dict] = Field(default_factory=dict)
    tokens_used: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    layer_timings: dict[str,Any] = Field(default_factory=dict)
    status: str = "ok" # ok | blocked | rejected    



