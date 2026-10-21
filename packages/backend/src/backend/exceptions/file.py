from backend.exceptions.base import AppException


class FileNotFoundException(AppException):
  status_code = 404
  code = 'FILE_NOT_FOUND'
  message = '파일을 찾을 수 없습니다.'
