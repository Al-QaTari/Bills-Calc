"""
Dependency injection container for the Treasury Bills Calculator application.
حاوية حقن التبعيات لتطبيق حاسبة أذون الخزانة.
"""

import os
from typing import Dict, Type, Any
from treasury_core.ports import YieldDataSource, HistoricalDataStore
from cbe_scraper import CbeScraper
from db_manager import SQLiteDBManager
from postgres_manager import PostgresDBManager


class DependencyContainer:
    """
    Central dependency management for the application.
    مركز إدارة التبعيات للتطبيق.
    """

    def __init__(self):
        """Initialize the dependency container."""
        self._instances: Dict[Type, Any] = {}
        self._factories = {
            YieldDataSource: self._create_data_source,
            HistoricalDataStore: self._create_data_store,
        }

    def get(self, interface_type):
        """
        Get an object implementing the specified interface.

        Args:
            interface_type: The interface type to resolve

        Returns:
            An instance implementing the interface

        Raises:
            ValueError: If the interface type cannot be created
        """
        if interface_type not in self._instances:
            if interface_type not in self._factories:
                raise ValueError(f"لا يمكن إنشاء كائن من النوع {interface_type}")
            self._instances[interface_type] = self._factories[interface_type]()
        return self._instances[interface_type]

    def _create_data_source(self) -> YieldDataSource:
        """
        Create the appropriate data source.

        Returns:
            A data source instance
        """
        return CbeScraper()

    def _create_data_store(self) -> HistoricalDataStore:
        """
        Create the appropriate data store based on settings.

        Returns:
            A data store instance (PostgreSQL or SQLite)
        """
        if os.environ.get("POSTGRES_URI"):
            return PostgresDBManager()
        else:
            return SQLiteDBManager()


# Global container instance for use throughout the application
container = DependencyContainer()
