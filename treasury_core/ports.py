"""
Port interfaces for the Treasury Bills Calculator application.
واجهات المنافذ لتطبيق حاسبة أذون الخزانة.
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple
import pandas as pd


class YieldDataSource(ABC):
    """
    Port representing any source that can fetch latest yield data.
    منفذ يمثل أي مصدر يمكنه جلب أحدث بيانات العوائد.
    """

    @abstractmethod
    def get_latest_yields(self) -> Optional[pd.DataFrame]:
        """
        Fetch the latest yield data.
        يجلب أحدث بيانات العوائد.

        Returns:
            DataFrame containing latest yield data or None if unavailable
        """
        pass


class HistoricalDataStore(ABC):
    """
    Port representing any storage that can save and load yield data.
    منفذ يمثل أي مكان يمكن فيه تخزين وتحميل بيانات العوائد.
    """

    @abstractmethod
    def save_data(self, df: pd.DataFrame) -> None:
        """
        Save new yield data.
        يحفظ بيانات العوائد الجديدة.

        Args:
            df: DataFrame containing yield data to save
        """
        pass

    @abstractmethod
    def load_latest_data(
        self,
    ) -> Tuple[pd.DataFrame, Tuple[Optional[str], Optional[str]]]:
        """
        Load the latest available data for each tenor.
        يقوم بتحميل أحدث البيانات المتاحة لكل أجل.

        Returns:
            Tuple of (DataFrame with latest data, (latest_date, latest_session_date))
        """
        pass

    @abstractmethod
    def load_all_historical_data(self) -> pd.DataFrame:
        """
        Load all historical data.
        يقوم بتحميل جميع البيانات التاريخية.

        Returns:
            DataFrame containing all historical data
        """
        pass

    @abstractmethod
    def get_latest_session_date(self) -> Optional[str]:
        """
        Get the latest session date recorded in the database.
        يجلب أحدث تاريخ جلسة مسجل في قاعدة البيانات.

        Returns:
            Latest session date string or None if no data available
        """
        pass
