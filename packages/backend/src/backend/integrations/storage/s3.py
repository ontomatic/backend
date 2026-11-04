from functools import lru_cache
from typing import BinaryIO
from urllib.parse import quote

import boto3
from backend.core.config import get_settings
from backend.core.logger import get_logger
from backend.integrations.storage.interface import ObjectInfo, Storage
from botocore.client import ClientError, Config

logger = get_logger(__file__)
settings = get_settings()


class S3Storage(Storage):
  def __init__(self, bucket: str):
    self._client = boto3.client(
      's3',
      endpoint_url=settings.s3_endpoint_url,
      aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
      aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
      region_name=settings.s3_region,
      config=Config(signature_version='s3v4', s3={'addressing_style': settings.s3_addressing_style}),
    )
    self._bucket = bucket

  def get_upload_url(self, key: str, *, content_type: str, expires_in: int = 3600) -> str:
    try:
      response = self._client.generate_presigned_url(
        'put_object',
        Params={'Bucket': self._bucket, 'Key': key, 'ContentType': content_type},
        ExpiresIn=expires_in,
      )
    except ClientError:
      logger.exception('Failed to issue upload url')
      raise

    return response

  def download(self, key: str, destination: BinaryIO) -> None:
    self._client.download_fileobj(self._bucket, key, destination)

  def copy(self, source_key: str, destination_key: str, *, source_etag: str | None = None) -> None:
    conditions = {'CopySourceIfMatch': source_etag} if source_etag else {}
    self._client.copy(
      CopySource={'Bucket': self._bucket, 'Key': source_key},
      Bucket=self._bucket,
      Key=destination_key,
      ExtraArgs=conditions,
    )

  def delete(self, key: str) -> None:
    self._client.delete_object(Bucket=self._bucket, Key=key)

  def get_download_url(self, key: str, *, filename: str, expires_in: int = 3600) -> str:
    return self._client.generate_presigned_url(
      'get_object',
      Params={
        'Bucket': self._bucket,
        'Key': key,
        'ResponseContentDisposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
        'ResponseContentType': 'application/octet-stream',
      },
      ExpiresIn=expires_in,
    )

  def get_object_info(self, key: str) -> ObjectInfo:
    object = self._client.head_object(Bucket=self._bucket, Key=key)
    return ObjectInfo(size=object['ContentLength'], content_type=object.get('ContentType'), etag=object.get('ETag'))


@lru_cache
def get_storage(bucket: str) -> Storage:
  return S3Storage(bucket=bucket)
