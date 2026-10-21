from abc import abstractmethod
from typing import BinaryIO, Protocol


class Storage(Protocol):
  @abstractmethod
  def get_upload_url(self, key: str, *, content_type: str, expires_in: int = 3600) -> str: ...

  @abstractmethod
  def download(self, key: str, destination: BinaryIO) -> None: ...

  @abstractmethod
  def delete(self, key: str) -> None: ...

  @abstractmethod
  def get_download_url(self, key: str, *, expires_in: int = 3600) -> str: ...
