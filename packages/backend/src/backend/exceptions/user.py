from backend.exceptions.base import AppException


class UserNotFoundException(AppException):
  status_code = 404
  code = 'USER_NOT_FOUND'
  message = '사용자를 찾을 수 없습니다.'


class DuplicateEmployeeIdException(AppException):
  status_code = 409
  code = 'EMP_ID_ALREADY_EXISTS'
  message = '이미 등록된 사번입니다.'


class InvalidDepartmentException(AppException):
  status_code = 422
  code = 'INVALID_DEPARTMENT'
  message = '배정할 수 있는 활성 부서를 지정해야 합니다.'
