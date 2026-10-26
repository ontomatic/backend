from backend.exceptions.base import AppException


class InvalidCredentialsException(AppException):
  status_code = 401
  code = 'INVALID_CREDENTIALS'
  message = '사번 또는 비밀번호가 올바르지 않습니다.'


class InsufficientPermissionsException(AppException):
  status_code = 403
  code = 'FORBIDDEN'
  message = '이 작업을 수행할 권한이 없습니다.'
