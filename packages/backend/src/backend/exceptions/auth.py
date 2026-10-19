from backend.exceptions.base import AppException


class InvalidCredentialsException(AppException):
  status_code = 401
  code = 'INVALID_CREDENTIALS'
  message = '사번 또는 비밀번호가 올바르지 않습니다.'
