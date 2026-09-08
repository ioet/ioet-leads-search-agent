"""Pluggable job-posting source interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.common.schemas import Company, JobPosting


class JobPostingSource(ABC):
    """Search a single external channel for open roles at a company."""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Stable registry id (e.g. ``linkedin``, ``company_website``)."""

    @abstractmethod
    def search(self, company: Company, *, max_results: int = 10) -> list[JobPosting]:
        """Return public job postings for the company (may be empty)."""
