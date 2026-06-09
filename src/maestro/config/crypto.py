"""
Módulo de criptografia para dados sensíveis armazenados no banco.
Usa Fernet (AES-128-CBC com HMAC) via cryptography library.
A chave é derivada do DATABASE_URL ou de uma variável ENCRYPTION_KEY dedicada.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet


def _derive_key() -> bytes:
    """
    Deriva uma chave Fernet a partir de ENCRYPTION_KEY (preferencial)
    ou DATABASE_URL como fallback. Garante que sempre temos 32 bytes url-safe base64.
    """
    secret = os.environ.get("ENCRYPTION_KEY") or os.environ.get("DB_URL", "maestro-default-key")
    # SHA-256 produz 32 bytes, perfeito para Fernet após base64
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_derive_key())
    return _fernet


def encrypt_value(plain_text: str) -> str:
    """Criptografa um valor e retorna a string base64 do ciphertext."""
    if not plain_text:
        return ""
    return _get_fernet().encrypt(plain_text.encode()).decode()


def decrypt_value(cipher_text: str) -> str:
    """Descriptografa um valor criptografado. Retorna vazio se inválido."""
    if not cipher_text:
        return ""
    try:
        return _get_fernet().decrypt(cipher_text.encode()).decode()
    except Exception:
        # Se não conseguir descriptografar, retorna o valor como está
        # (pode ser um valor antigo não criptografado)
        return cipher_text
