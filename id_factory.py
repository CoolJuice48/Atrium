from __future__ import annotations

import re
import uuid
import unicodedata
from dataclasses import dataclass

BOOK_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "eecs281.textbook")

""" -------------------------------------------------------------------------------------------------------- """
"""
Normalize strings for consistent IDs
Args:
    s: The input string to normalize
Returns:
    A normalized string suitable for use in IDs
"""
def _norm(s: str) -> str:
    s = unicodedata.normalize('NFKC', s or '')
    s = s.strip().lower()
    s = re.sub(r'\s+', ' ', s)  # Replace multiple whitespace with single space
    return s

""" -------------------------------------------------------------------------------------------------------- """
"""
Deterministic, namespaced IDs
"""
class IDFactory:
    PROJECT_SALT: str = "pdf_processor_v1"
    PROJECT_NAMESPACE: str = str(uuid.UUID('12345678-1234-5678-1234-567812345678'))  # Fixed namespace for all IDs in this project
    @staticmethod
    def _ns() -> uuid.UUID:
        return uuid.uuid5(uuid.UUID(IDFactory.PROJECT_NAMESPACE), IDFactory.PROJECT_SALT)
    
    @staticmethod
    def book_id(book_key: str) -> str:
        name = f'book:{_norm(book_key)}'
        return str(uuid.uuid5(IDFactory._ns(), name))
    
    @staticmethod
    def section_id(book_id: str, section_key: str) -> str:
        name = f'section|book:{_norm(book_id)}|{_norm(section_key)}|key:{_norm(section_key)}'
        return str(uuid.uuid5(IDFactory._ns(), name))
    
    @staticmethod
    def page_id(book_id: str, page_number: int) -> str:
        name = f'page|book:{_norm(book_id)}|number:{int(page_number)}'
        return str(uuid.uuid5(IDFactory._ns(), name))
    
    @staticmethod
    def qa_id(book_id: str, problem_key: str) -> str:
        name = f'qa|book:{_norm(book_id)}|problem:{_norm(problem_key)}'
        return str(uuid.uuid5(IDFactory._ns(), name))