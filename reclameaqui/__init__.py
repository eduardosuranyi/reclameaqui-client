"""Cliente da API interna do Reclame Aqui."""
from .client import Client, ReclameAquiError, strip_pii

__all__ = ["Client", "ReclameAquiError", "strip_pii"]
__version__ = "0.1.0"
