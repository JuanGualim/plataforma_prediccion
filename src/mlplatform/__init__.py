"""mlplatform: la plataforma interna de MLOps.

Regla de dependencias: este paquete NUNCA importa de `use_cases`.
Los casos de uso dependen de la plataforma, no al revés
(verificado en tests/unit/test_architecture.py).
"""

__version__ = "0.1.0"
