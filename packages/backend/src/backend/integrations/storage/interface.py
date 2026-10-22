from abc import abstractmethod
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol


@dataclass
class ObjectInfo:
  size: int
  content_type: str


class Storage(Protocol):
  @abstractmethod
  def get_upload_url(self, key: str, *, content_type: str, expires_in: int = 3600) -> str: ...

  @abstractmethod
  def download(self, key: str, destination: BytesIO) -> None: ...

  @abstractmethod
  def delete(self, key: str) -> None: ...

  @abstractmethod
  def get_download_url(self, key: str, *, expires_in: int = 3600) -> str: ...

  @abstractmethod
  def get_object_info(self, key: str) -> ObjectInfo: ...
