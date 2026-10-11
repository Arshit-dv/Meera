"""
Meera - ModelProvider Interface
Abstract base class defining the uniform contract for model inference backends.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional


@dataclass
class ChatMessage:
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class GenerationRequest:
    messages: List[ChatMessage]
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 512
    stream: bool = False
    stop: Optional[List[str]] = None


@dataclass
class GenerationResponse:
    content: str
    finish_reason: Optional[str] = "stop"
    usage: Dict[str, int] = field(default_factory=dict)


@dataclass
class StreamChunk:
    delta: str
    finish_reason: Optional[str] = None


class ModelProvider(ABC):
    """
    Uniform abstract provider contract.
    The Agent Core communicates only through this interface, keeping Meera model-agnostic.
    """

    @abstractmethod
    def load(self) -> bool:
        """Loads or starts the underlying model runtime."""
        pass

    @abstractmethod
    def unload(self) -> bool:
        """Unloads or stops the underlying model runtime to reclaim RAM/VRAM."""
        pass

    @abstractmethod
    def is_loaded(self) -> bool:
        """Checks whether the model runtime is active and ready."""
        pass

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Executes non-streaming completion."""
        pass

    @abstractmethod
    def stream(self, request: GenerationRequest) -> Iterator[StreamChunk]:
        """Executes streaming completion."""
        pass

    @abstractmethod
    def health(self) -> Dict[str, Any]:
        """Returns health and status metadata."""
        pass
